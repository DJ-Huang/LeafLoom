"""Conservative public Asset Store collection; HTML is data, never executable.

Collection has no purchase-account, browser-cookie or NAS-credential access.
Unknown metadata stays unknown. A filename is only a search hint, never proof of
identity; automatic associations require one exact official title/publisher pair.
"""
from __future__ import annotations

import hashlib
import http.client
from html import unescape
from html.parser import HTMLParser
import ipaddress
import io
import json
from pathlib import Path, PurePosixPath
import re
import ssl
import sys
import threading
import tempfile
import time
import unicodedata
from urllib.parse import quote, urljoin, urlsplit
import urllib.request
import uuid

from PIL import Image, ImageOps

from vault_rag.file_downloads import PinnedHTTPSConnection, public_target
from vault_rag.local_state import atomic_write, ConflictError


class OfficialSourceError(ValueError):
    def __init__(self, code):
        self.code=code
        super().__init__(code)


def official_url(value):
    try:parsed=urlsplit(value)
    except ValueError:raise ValueError('Use an official Unity Asset Store product URL') from None
    if (parsed.scheme!='https' or parsed.hostname!='assetstore.unity.com' or parsed.port not in (None,443)
            or parsed.username or parsed.password):
        raise ValueError('Use an official Unity Asset Store product URL')
    match=re.fullmatch(r'/(?:en-US/|zh-CN/|ja-JP/|ko-KR/)?packages/(?:package/|(?:[a-zA-Z0-9_%.-]+/)*[a-zA-Z0-9_%.-]+-)([1-9][0-9]{0,17})/?',parsed.path)
    if not match:raise ValueError('Use an official Unity Asset Store product URL with a product ID')
    return 'unity.assetstore:'+match[1], 'https://assetstore.unity.com'+parsed.path.rstrip('/')


def normalized(value):
    return re.sub(r'[^a-z0-9\u3400-\u9fff]+','',unicodedata.normalize('NFKC',str(value)).casefold())


def package_hint(item):
    path=item.get('remote_path') or item.get('path','')
    parts=PurePosixPath(path).parts
    filename=item.get('name') or PurePosixPath(path).name
    title=re.sub(r'\.unitypackage$','',filename,flags=re.I)
    title=re.sub(r'\s+v?\d+(?:\.\d+){1,3}(?:\s*\([^)]*\))?$','',title)
    publisher=''
    for index,part in enumerate(parts[:-1]):
        if part.lower().startswith('asset store-') and index+1<len(parts)-1:
            following=parts[index+1]
            if not following.lower().startswith('asset store-'):publisher=following
    return title,publisher


class ProductPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta={};self.json=[];self.links=[];self.hydration=[];self.search_links=[];self.search_cards=[];self.is_search=False
        self._result_article=False;self._search_anchor=None;self._script=None;self._parts=[]

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='meta':
            key=attrs.get('property',attrs.get('name','')).lower()
            if key:self.meta.setdefault(key,attrs.get('content',''))
        if tag=='article' and attrs.get('data-test','').startswith('search-results-product-card-'):self._result_article=True
        if attrs.get('data-test')=='search-page-title':self.is_search=True
        if tag=='a' and attrs.get('href'):
            self.links.append(attrs['href'])
            if self._result_article and attrs.get('data-test')=='product-card-name':
                self.search_links.append(attrs['href']);self._search_anchor={'href':attrs['href'],'title':attrs.get('title',''),'parts':[]}
        if tag=='script' and not attrs.get('src'):
            self._script='ld' if attrs.get('type','').lower()=='application/ld+json' else 'hydration';self._parts=[]

    def handle_data(self,value):
        if self._script:self._parts.append(value)
        if self._search_anchor is not None:self._search_anchor['parts'].append(value)

    def handle_endtag(self,tag):
        if tag=='a' and self._search_anchor is not None:
            card=self._search_anchor;self._search_anchor=None
            self.search_cards.append({'href':card['href'],'title':_text(' '.join(card['parts'])) or _text(card['title'])})
        if tag=='script' and self._script:
            source=''.join(self._parts)
            try:
                if self._script=='ld':self.json.append(json.loads(source))
                else:
                    marker='.ReactDOMrender('
                    if marker in source:
                        value,_=json.JSONDecoder().raw_decode(source.split(marker,1)[1].lstrip())
                        if isinstance(value,dict):self.hydration.append(value)
            except (ValueError,TypeError,RecursionError):pass
            self._script=None;self._parts=[]
        if tag=='article':self._result_article=False


def _nodes(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():yield from _nodes(child)
    elif isinstance(value,list):
        for child in value:yield from _nodes(child)


def _text(value,limit=10000):
    if not isinstance(value,str):return ''
    return re.sub(r'\s+',' ',unescape(re.sub(r'<[^>]*>',' ',value))).strip()[:limit]


def _reference(entities,value,table):
    if not isinstance(value,dict) or value.get('type')!='id':return {}
    identity=value.get('id')
    if not isinstance(identity,list) or len(identity)!=2 or identity[0]!=table:return {}
    values=entities.get(table,{})
    result=values.get(str(identity[1]),{}) if isinstance(values,dict) else {}
    return result if isinstance(result,dict) else {}


def _product_details(page,product_id,title,publisher):
    for state in page.hydration:
        data=state.get('data',{})
        entities=data.get('ENTITY',{}) if isinstance(data,dict) else {}
        if not isinstance(entities,dict):continue
        values=entities.get('Product',{})
        product=values.get(product_id.removeprefix('unity.assetstore:'),{}) if isinstance(values,dict) else {}
        if not isinstance(product,dict) or not product:continue
        author=_reference(entities,product.get('publisher'),'ProductPublisher')
        if (str(product.get('id'))!=product_id.removeprefix('unity.assetstore:') or normalized(product.get('name'))!=normalized(title)
                or normalized(author.get('name'))!=normalized(publisher)):
            raise OfficialSourceError('official_product_id_mismatch')
        return product,entities
    return {},{}


def parse_product(html,url):
    product_id,url=official_url(url)
    page=ProductPage();page.feed(html)
    products=[n for v in page.json for n in _nodes(v) if n.get('@type')=='Product' or
              isinstance(n.get('@type'),list) and 'Product' in n['@type']]
    # Some official pages omit JSON-LD but retain their normalized public
    # Product/Publisher entities. OpenGraph alone never proves an identity.
    if not products:
        identities=[]
        for state in page.hydration:
            data=state.get('data',{})
            entities=data.get('ENTITY',{}) if isinstance(data,dict) else {}
            if not isinstance(entities,dict):continue
            table=entities.get('Product',{})
            details=table.get(product_id.removeprefix('unity.assetstore:'),{}) if isinstance(table,dict) else {}
            if not isinstance(details,dict) or str(details.get('id'))!=product_id.removeprefix('unity.assetstore:'):continue
            author=_reference(entities,details.get('publisher'),'ProductPublisher')
            publisher_reference=details.get('publisher',{})
            reference=publisher_reference.get('id',[]) if isinstance(publisher_reference,dict) else []
            if (not _text(details.get('name',''),500) or not _text(author.get('name',''),500)
                    or len(reference)!=2 or str(author.get('id',''))!=str(reference[1])):continue
            identities.append((details['name'],author['name'],str(author['id'])))
        if identities and len(set(identities))==1:
            title,publisher,_=identities[0]
            products=[{'name':title,'brand':{'name':publisher},'url':page.meta.get('og:url') or url}]
    if len(products)!=1:raise OfficialSourceError('official_product_data_unavailable')
    product=products[0]
    canonical=product.get('url') or page.meta.get('og:url') or (product.get('offers') or {}).get('url')
    if canonical:
        try:
            canonical_id,canonical_url=official_url(urljoin(url,canonical))
            if canonical_id!=product_id:raise OfficialSourceError('official_product_id_mismatch')
            url=canonical_url
        except ValueError:raise OfficialSourceError('official_product_id_mismatch') from None
    publisher=product.get('brand') or product.get('manufacturer') or product.get('author')
    if isinstance(publisher,dict):publisher=publisher.get('name')
    title=_text(product.get('name',''),500);publisher=_text(publisher,500)
    if not title or not publisher:raise OfficialSourceError('official_identity_incomplete')
    details,entities=_product_details(page,product_id,title,publisher)
    description=_text(details.get('description') or product.get('description') or page.meta.get('description',''))
    if re.match(r'(?:Elevate your workflow|Find this & other)',description,re.I):description=''
    # Keep a short source excerpt for a faithful summary, never a complete long
    # copyrighted description. Chinese summaries are separate explicit metadata.
    excerpt=' '.join(description.split()[:180])[:1200]
    categories=product.get('category') or []
    if isinstance(categories,str):categories=[categories]
    if not categories:
        for node in (n for value in page.json for n in _nodes(value) if n.get('@type')=='BreadcrumbList'):
            crumbs=node.get('itemListElement',[])
            if isinstance(crumbs,list):
                labels=[_text(crumb.get('name'),200) for crumb in crumbs[1:-1] if isinstance(crumb,dict)]
                if labels:categories=['/'.join(labels)];break
    if not categories and details:
        category=_reference(entities,details.get('category'),'Category')
        if category.get('name'):categories=[category['name']]
    keywords=product.get('keywords') or []
    if isinstance(keywords,str):keywords=[v.strip() for v in keywords.split(',') if v.strip()]
    if not keywords and details:
        keywords=[tag.get('name','') for ref in details.get('popularTags',[]) if (tag:=_reference(entities,ref,'ProductTag'))]
    image=product.get('image') or page.meta.get('og:image','')
    if isinstance(image,list):image=image[0] if image else ''
    if isinstance(image,dict):image=image.get('url','')
    compatibility={}
    if details:
        compatibility={'unity_versions':[_text(v,100) for v in details.get('supportedUnityVersions',[]) if isinstance(v,str)][:30],
                       'render_pipelines':[{'unity_version':_text(srp.get('version'),100),'pipelines':[_text(v,100) for v in srp.get('types',[]) if isinstance(v,str)][:10]}
                                           for srp in details.get('srps',[]) if isinstance(srp,dict)][:30],
                       'notes':_text(details.get('compatibilityInfo'),1200)}
    version=product.get('softwareVersion') or _reference(entities,details.get('currentVersion'),'ProductVersion').get('name','')
    value={'product_id':product_id,'url':url,'title':title,'publisher':publisher,
           'categories':[_text(v,200) for v in categories if isinstance(v,str)][:30],
           'keywords':[_text(v,200) for v in keywords if isinstance(v,str)][:100],
           'summary_zh':'','source_excerpt':excerpt,'fetched_at':time.time(),
           'cover_source_url':urljoin(url,image) if image else '',
           'latest_version':_text(version,100),
           'compatibility':compatibility,'summary_status':'needs_summary'}
    return value


def _check_access_page(html):
    if re.search(r'<title[^>]*>\s*(?:just a moment|access denied|sign in|log in|verify you are human)',html,re.I) or re.search(
            r'<(?:form|div)[^>]+(?:id=["\']challenge-form["\']|class=["\']g-recaptcha["\'])',html,re.I):
        raise OfficialSourceError('official_source_access_required')


def _refresh_official(metadata,previous):
    """A public fact refresh cannot erase separately supplied translations."""
    metadata=dict(metadata)
    changed=any(key in metadata and metadata[key]!=previous.get(key)
                for key in ('title','publisher','source_excerpt','categories','keywords','latest_version','compatibility'))
    for key in ('summary_zh','categories_zh','keywords_zh'):
        if not metadata.get(key):metadata.pop(key,None)
    if not metadata.get('summary_zh') and previous.get('summary_zh'):
        if changed:metadata['summary_status']='needs_summary'
        elif previous.get('summary_status'):metadata['summary_status']=previous['summary_status']
        else:metadata.pop('summary_status',None)
    return metadata


_COVER_HOSTS={'unity-assetstorev2-prd.storage.googleapis.com','assetstorev1-prd-cdn.unity3d.com',
              'assetstorev1-prd-cdn.unity3d.com.cn'}


def _system_https_proxy():
    """Use an existing macOS loopback HTTP proxy, never environment settings."""
    if sys.platform!='darwin':return None
    reader=getattr(urllib.request,'getproxies_macosx_sysconf',None)
    if reader is None:return None
    value=reader().get('https')
    if not value:return None
    try:
        parsed=urlsplit(value)
        if (parsed.scheme!='http' or parsed.username or parsed.password or parsed.path not in ('','/')
                or parsed.query or parsed.fragment or not parsed.hostname or not parsed.port
                or not ipaddress.ip_address(parsed.hostname).is_loopback):raise ValueError('Unsupported system proxy')
        return parsed.hostname,parsed.port
    except (TypeError,ValueError):raise OfficialSourceError('official_source_proxy_configuration_rejected') from None


class UnityOfficialSource:
    def __init__(self,fetch=None):self.fetch=fetch or self._fetch

    @staticmethod
    def _fetch(url,*,image=False):
        limit=10*1024**2 if image else 5*1024**2
        for redirect in range(4):
            try:parsed=urlsplit(url)
            except ValueError:raise OfficialSourceError('official_source_host_rejected') from None
            allowed=parsed.hostname in _COVER_HOSTS if image else parsed.hostname=='assetstore.unity.com'
            try:
                if (not allowed or parsed.scheme!='https' or parsed.port not in (None,443) or parsed.username or parsed.password
                        or len(url)>16384 or any(ord(c)<33 for c in url)):raise ValueError('Invalid official URL')
            except ValueError:raise OfficialSourceError('official_source_host_rejected') from None
            proxy=_system_https_proxy()
            if proxy:
                # HTTPSConnection verifies the target certificate and sends SNI
                # for the tunnel host. The proxy resolves only fixed official
                # targets; fake-IP local DNS is never treated as public DNS.
                connection=http.client.HTTPSConnection(*proxy,timeout=30,context=ssl.create_default_context())
                connection.set_tunnel(parsed.hostname,443)
                path,query=parsed.path or '/',parsed.query
            else:
                host,address,path,query=public_target(url)
                connection=PinnedHTTPSConnection(host,address)
            try:
                connection.request('GET',path+('?' + query if query else ''),headers={
                    'Accept-Encoding':'identity','User-Agent':'LeafLoom-AssetCatalog/1.0',
                    'Accept':'image/*' if image else 'text/html'})
                response=connection.getresponse()
                if response.status in (301,302,303,307,308):
                    location=response.getheader('Location')
                    if not location or redirect==3:raise OfficialSourceError('official_source_redirect_rejected')
                    url=urljoin(url,location);continue
                if response.status==429:raise OfficialSourceError('official_source_rate_limited')
                if response.status in (401,403):raise OfficialSourceError('official_source_access_required')
                if response.status in (404,410):raise OfficialSourceError('official_product_unavailable')
                if response.status!=200:raise OfficialSourceError('official_source_unavailable')
                content_type=response.getheader('Content-Type','').split(';')[0].lower()
                if not (content_type.startswith('image/') if image else content_type=='text/html'):
                    raise OfficialSourceError('official_source_content_rejected')
                if response.getheader('Content-Encoding','identity')!='identity':
                    raise OfficialSourceError('official_source_encoding_rejected')
                data=response.read(limit+1)
                if len(data)>limit:raise OfficialSourceError('official_source_too_large')
                return data
            finally:connection.close()
        raise OfficialSourceError('official_source_unavailable')

    def product(self,url):
        _,url=official_url(url)
        html=self.fetch(url).decode('utf-8','replace');_check_access_page(html)
        return parse_product(html,url)

    def search(self,title,publisher):
        # Only public official links are candidates. Product pages are separately
        # fetched and their structured identity must exactly match both hints.
        html=self.fetch('https://assetstore.unity.com/en-US/search?q='+quote(_text(title,500))).decode('utf-8','replace')
        _check_access_page(html)
        page=ProductPage();page.feed(html)
        result={}
        if not page.is_search and not page.search_links:raise OfficialSourceError('official_search_data_unavailable')
        for card in page.search_cards:
            if normalized(card['title'])!=normalized(title):continue
            try:
                product_id,url=official_url(urljoin('https://assetstore.unity.com/',card['href']))
            except ValueError:continue
            result[product_id]=url
        return list(result.values())[:12]

    def cover(self,url):
        raw=self.fetch(url,image=True)
        try:
            with Image.open(io.BytesIO(raw)) as picture:
                if picture.width*picture.height>25_000_000:raise ValueError('Image dimensions are too large')
                picture.verify()
            with Image.open(io.BytesIO(raw)) as picture:
                picture=ImageOps.exif_transpose(picture).convert('RGB')
                picture.thumbnail((1200,900))
                output=io.BytesIO();picture.save(output,'WEBP',quality=88)
                return output.getvalue()
        except (OSError,ValueError,Image.DecompressionBombError):
            raise OfficialSourceError('official_cover_invalid') from None


class AssetEnrichment:
    """Resumable, serial metadata-only enrichment. Never downloads package bodies."""
    def __init__(self,library,source=None):
        self.library=library;self.remote=library.remote
        self.source=source or UnityOfficialSource()
        self.lock=threading.RLock();self.stopped=threading.Event();self.threads={}

    def _path(self,root):
        self.remote._root(root)
        path=self.remote._files().state_path('asset-library','enrichment.json')
        self.remote._root(root)
        return path

    def status(self,root):
        with self.lock:
            path=self._path(root)
            return json.loads(path.read_text()) if path.exists() else {'state':'idle','total':0,'succeeded':0,'needs_review':0,'failed':0,'results':[]}

    def _save(self,root,value):
        with self.lock:atomic_write(self._path(root),json.dumps(value,ensure_ascii=False).encode())

    def record_blocked(self,root,reason='browser_origin_permission',*,guard=None):
        """Stage a truthful pending inventory without contacting a blocked site."""
        if guard:guard()
        items=[];cursor=''
        while True:
            page=self.library.listing(root,limit=200,cursor=cursor)
            items.extend(item for item in page['items'] if item.get('kind')=='candidate')
            cursor=page.get('next_cursor','')
            if not cursor:break
        value={'job_id':uuid.uuid4().hex,'state':'paused','error':reason,'total':len(items),
               'succeeded':0,'needs_review':len(items),'failed':0,
               'results':[{'id':item['id'],'state':'needs_review','reason':reason} for item in items]}
        self._save(root,value)
        return value

    def _review(self,root,item_id,reason,owner,operation_id,**fields):
        return self.library.update(root,'review',{'id':item_id,'status':'needs_review','reason':reason,**fields},
                                   owner=owner,operation_id=operation_id)

    def official_url(self,root,url,*,item_id='',asset_id='',owner='local',operation_id='',expected_revision='',guard=None,
                     _verified_data=None):
        if guard:guard()
        candidate=self.library.detail(root,item_id) if item_id else None
        if candidate and expected_revision and candidate['revision']!=expected_revision:
            raise ConflictError('Product metadata changed; reload before associating')
        product_id,url=official_url(url)
        value=self.source.product(url) if _verified_data is None else _verified_data
        if str(value.get('product_id','')).removeprefix('unity.assetstore:')!=product_id.removeprefix('unity.assetstore:'):
            raise OfficialSourceError('official_product_id_mismatch')
        if guard:guard()
        metadata={key:content for key,content in value.items() if key!='cover_source_url'}
        try:previous=self.library.detail(root,product_id)
        except FileNotFoundError:previous=None
        metadata=_refresh_official(metadata,previous['official'] if previous else {})
        existing=self.library.update(root,'official',{'product_id':product_id,'official':metadata},
            owner=owner,operation_id=(operation_id or uuid.uuid4().hex)+':official',
            expected_revision=previous['revision'] if previous else '')
        pending_match=None
        if asset_id:
            # Manual URL establishes a candidate, not an automatic identity claim.
            files=candidate.get('files',[]) if candidate else [self.remote.stat(root,asset_id=asset_id)]
            hints=[package_hint(file) for file in files]
            exact=bool(hints) and all(normalized(title)==normalized(value['title']) and publisher and
                    normalized(publisher)==normalized(value['publisher']) for title,publisher in hints)
            if exact:
                for file in files:
                    if guard:guard()
                    self.library.update(root,'bind',{'product_id':product_id,'asset_id':file['asset_id'],
                        'evidence':{'method':'official_title_publisher','url':url}},owner=owner,
                        operation_id=(operation_id or uuid.uuid4().hex)+':bind:'+file['asset_id'],
                        expected_revision=candidate['revision'] if candidate and candidate['kind']=='candidate' else '')
                self.library.update(root,'review',{'product_id':product_id,'status':'confirmed',
                    'reason':'official_title_publisher_match'},owner=owner,
                    operation_id=(operation_id or uuid.uuid4().hex)+':confirmed')
            elif item_id:
                self._review(root,item_id,'official_identity_requires_confirmation',owner,
                             (operation_id or uuid.uuid4().hex)+':review',proposed_product_id=product_id.removeprefix('unity.assetstore:'),
                             proposed_url=url,evidence={'method':'user_supplied_official_url'})
                pending_match={'candidate_id':item_id,'asset_id':asset_id,'product_id':product_id,'url':url}
                pending_match['candidate_revision']=self.library.detail(root,item_id)['revision']
        warnings=[]
        if value.get('cover_source_url'):
            try:
                content=self.source.cover(value['cover_source_url'])
                store=getattr(self.library,'store_cover',None)
                if store:
                    with tempfile.TemporaryDirectory(prefix='asset-cover-',dir=self.remote.config.directory) as directory:
                        file=Path(directory)/'official.webp';file.write_bytes(content)
                        store(root,product_id,file,value['cover_source_url'],owner=owner)
            except (OfficialSourceError,OSError,ValueError) as error:
                # A bad refresh cannot replace an existing valid official cover.
                warnings.append(error.code if isinstance(error,OfficialSourceError) else 'official_cover_unavailable')
        result=self.library.detail(root,product_id)
        if pending_match:result['pending_match']=pending_match
        if warnings:result['collection_warnings']=warnings
        return result

    @staticmethod
    def missing_fields(item):
        official=item.get('official',{})
        missing=[]
        if not official.get('cover'):missing.append('cover')
        if not (official.get('keywords') or official.get('keywords_zh')):missing.append('tags')
        if not (official.get('summary_zh') or official.get('description') or official.get('source_excerpt')):missing.append('description')
        return missing

    @staticmethod
    def _scope(item_ids,limit,refresh,delay):
        if item_ids is not None:
            if (not isinstance(item_ids,list) or len(item_ids)>100000 or any(not isinstance(identity,str) or
                    not re.fullmatch(r'(?:candidate:[0-9a-f]{32}|unity\.assetstore:[1-9][0-9]{0,17})',identity) for identity in item_ids)):
                raise ValueError('Invalid collection item IDs')
            item_ids=sorted(set(item_ids))
        if type(limit)is not int or not 0<=limit<=100000:raise ValueError('Use a collection limit from 0 through 100000')
        if type(refresh)is not bool:raise ValueError('Invalid collection refresh flag')
        if type(delay) not in (int,float) or not .5<=delay<=60:raise ValueError('Use a collection delay from 0.5 through 60 seconds')
        return {'item_ids':item_ids,'limit':limit,'refresh':refresh,'delay_seconds':delay}

    def _inventory(self,root):
        items=[];cursor=''
        while True:
            page=self.library.listing(root,limit=500,cursor=cursor)
            items.extend(page['items']);cursor=page.get('next_cursor','')
            if not cursor:return items

    def _select(self,items,scope):
        allowed=set(scope['item_ids']) if scope['item_ids'] is not None else None
        selected=[item for item in items if (allowed is None or item['id'] in allowed) and not item.get('conflicts')
                  and item.get('files') and (not item.get('product_id') or scope['refresh'] or self.missing_fields(item))]
        return selected[:scope['limit']] if scope['limit'] else selected

    def plan(self,root,*,item_ids=None,limit=0,refresh=False,delay=1):
        """Local inventory only: no store requests, events or collection checkpoint."""
        scope=self._scope(item_ids,limit,refresh,delay)
        items=self._select(self._inventory(root),scope)
        return {'state':'preview','total':len(items),
                'candidates':sum(not item.get('product_id') for item in items),
                'products':sum(bool(item.get('product_id')) for item in items),
                'items':[{'id':item['id'],'missing_fields':self.missing_fields(item)} for item in items]}

    @staticmethod
    def _input(item):
        identity=item['id'];uid=identity.removeprefix('candidate:')
        if not re.fullmatch('[0-9a-f]{32}',uid):uid=''
        return {'id':identity,'file_uid':uid}

    def _recover_input(self,root,item,active):
        result={'id':item['id'],'state':'needs_review','reason':'candidate_unavailable'}
        if not item.get('file_uid'):return result
        identity=self.library.collection_identity(root,item['file_uid'])
        if not isinstance(identity,dict) or identity.get('availability')!='ready':return result
        if not identity.get('product_id'):return result
        result['reason']='candidate_binding_changed'
        if not isinstance(active,dict) or active.get('id')!=item['id'] or active.get('file_uid')!=item['file_uid'] or identity.get('conflict'):return result
        try:
            product_id=str(active['product_id']).removeprefix('unity.assetstore:')
            official=identity['official'];evidence=identity['evidence']
            matching=(identity['product_id']==product_id and str(official.get('product_id','')).removeprefix('unity.assetstore:')==product_id
                      and official.get('title')==active['title'] and official.get('publisher')==active['publisher']
                      and evidence.get('method')=='official_title_publisher'
                      and official_url(evidence.get('url',''))==official_url(active['url'])
                      and official_url(official.get('url',''))==official_url(active['url']))
        except (KeyError,TypeError,ValueError):matching=False
        if matching:return {'id':item['id'],'state':'succeeded','product_id':'unity.assetstore:'+product_id,'reason':'checkpoint_recovered'}
        return result

    def start(self,root,*,owner='local',guard=None,item_ids=None,limit=0,refresh=False,delay=1):
        if guard:guard()
        scope=self._scope(item_ids,limit,refresh,delay)
        with self.lock:
            old=self.status(root)
            if root in self.threads and self.threads[root].is_alive():
                if old.get('scope',self._scope(None,0,False,1))!=scope:
                    raise ConflictError('A collection with a different scope is already running')
                return old
            if old.get('scope',self._scope(None,0,False,1))!=scope:old={}
            recovering=old.get('state') in {'running','interrupted'}
            items=self._inventory(root)
            candidates={item['id']:item for item in self._select(items,scope)}
            def completed(result):
                if result.get('state')=='succeeded':
                    # A previous success does not conceal a still-incomplete
                    # product, or prevent an explicit new refresh.
                    return not (result['id'].startswith('unity.assetstore:') and result['id'] in candidates)
                reason=result.get('reason','')
                return (recovering and result.get('state')=='needs_review' and isinstance(reason,str) and bool(reason)
                        and reason not in {'browser_origin_permission','authorization_changed','workspace_changed','official_metadata_incomplete'}
                        and not reason.startswith('official_source_'))
            previous={r['id']:r for r in old.get('results',[]) if completed(r)}
            if recovering and isinstance(old.get('inputs'),list):
                inputs={item['id']:item for item in old['inputs'] if isinstance(item,dict) and isinstance(item.get('id'),str)}
            else:
                inputs={identity:self._input({'id':identity}) for identity in previous}
                inputs.update({identity:self._input(item) for identity,item in candidates.items()})
            if isinstance(old.get('active'),dict) and isinstance(old['active'].get('id'),str):
                inputs.setdefault(old['active']['id'],self._input(old['active']))
            pending=[]
            current={item['id']:item for item in items}
            for identity,item in inputs.items():
                if identity in previous:continue
                if identity in candidates:pending.append(candidates[identity])
                elif identity.startswith('unity.assetstore:') and identity in current and not current[identity].get('conflicts'):
                    # Recheck a product interrupted after a partial metadata
                    # write; never infer success solely from an active marker.
                    pending.append(current[identity])
                else:previous[identity]=self._recover_input(root,item,old.get('active'))
            # A pre-checkpoint legacy journal cannot reveal a lost input ID.
            # Preserve its numeric baseline, never invent a successful result.
            baseline=old.get('total',0)
            total=max(len(inputs),baseline if recovering and type(baseline)is int and baseline>=0 else 0)
            job={'job_id':old.get('job_id') or uuid.uuid4().hex,'state':'running','scope':scope,'delay_seconds':delay,'total':total,'inputs':list(inputs.values()),
                 'succeeded':sum(r.get('state')=='succeeded' for r in previous.values()),
                 'needs_review':sum(r.get('state')=='needs_review' for r in previous.values()),'failed':0,'results':list(previous.values())}
            if total>len(inputs):job['legacy_unresolved']=total-len(inputs)
            if isinstance(old.get('active'),dict) and old['active'].get('id') in {item['id'] for item in pending}:job['active']=old['active']
            self._save(root,job)
            thread=threading.Thread(target=self._run,args=(root,pending,job,owner,guard),daemon=True,name='unity-catalog-enrichment')
            self.threads[root]=thread;thread.start()
            return job

    def _run(self,root,items,job,owner,guard):
        verified={};failures={}
        try:
            for item in items:
                if self.stopped.is_set():job['state']='interrupted';break
                if guard:guard()
                result={'id':item['id'],'state':'needs_review'}
                try:
                    if item.get('product_id'):
                        # A recorded product ID survives renames and publisher
                        # changes. Refresh it directly without rebinding files.
                        product_id,_=official_url('https://assetstore.unity.com/packages/package/'+str(item['product_id']).removeprefix('unity.assetstore:'))
                        key=('product',product_id)
                        if key not in verified:verified[key]=self.source.product('https://assetstore.unity.com/packages/package/'+product_id.removeprefix('unity.assetstore:'))
                        product=verified[key]
                        files=[]
                    else:
                        files=item.get('files') or self.library.detail(root,item['id']).get('files',[])
                        title,publisher=package_hint(files[0]) if files else ('','')
                        if not title:raise OfficialSourceError('publisher_or_title_unknown')
                        key=(normalized(title),normalized(publisher))
                        if key in failures:
                            if failures[key]=='official_collection_failed':raise ValueError('Official collection previously failed')
                            raise OfficialSourceError(failures[key])
                        if key not in verified:
                            try:
                                matches=[]
                                for url in self.source.search(title,publisher):
                                    product=self.source.product(url)
                                    if normalized(product['title'])==normalized(title) and (not publisher or normalized(product['publisher'])==normalized(publisher)):
                                        matches.append(product)
                                if len(matches)!=1:raise OfficialSourceError('ambiguous_or_unavailable_product')
                                verified[key]=matches[0]
                            except OfficialSourceError as error:failures[key]=error.code;raise
                            except (OSError,ValueError,ConflictError):failures[key]='official_collection_failed';raise
                        product=verified[key]
                        if not publisher:
                            self._review(root,item['id'],'publisher_requires_confirmation',owner,uuid.uuid4().hex,
                                proposed_product_id=product['product_id'].removeprefix('unity.assetstore:'),proposed_url=product['url'],
                                evidence={'method':'official_title_only'})
                            result['reason']='publisher_requires_confirmation'
                            job['results'].append(result);job['needs_review']+=1
                            self._save(root,job)
                            if self.stopped.wait(job.get('delay_seconds',.5)):job['state']='interrupted';break
                            continue
                    job['active']={**self._input(item),'product_id':product['product_id'],'url':product['url'],
                                   'title':product['title'],'publisher':product['publisher']}
                    self._save(root,job)  # Durable before any product metadata or binding mutation.
                    updated=self.official_url(root,product['url'],item_id=item['id'],asset_id=files[0]['asset_id'] if files else '',owner=owner,guard=guard,
                                              _verified_data=product,expected_revision=item.get('revision',''))
                    result['product_id']=product['product_id']
                    for warning in updated.get('collection_warnings',[]):
                        if warning in {'official_source_access_required','official_source_rate_limited'}:raise OfficialSourceError(warning)
                    missing=self.missing_fields(updated)
                    if missing:
                        result.update(reason='official_metadata_incomplete',missing_fields=missing)
                    else:result['state']='succeeded'
                except OfficialSourceError as error:
                    result['reason']=error.code
                    self._review(root,item['id'],error.code,owner,uuid.uuid4().hex)
                    if error.code in {'official_source_access_required','official_source_rate_limited'}:
                        job['state']='paused';job['error']=error.code
                except (OSError,ValueError,ConflictError):
                    result.update(state='failed',reason='official_collection_failed')
                job['results'].append(result)
                job[{'succeeded':'succeeded','needs_review':'needs_review','failed':'failed'}[result['state']]]+=1
                job.pop('active',None)
                self._save(root,job)
                if job['state']=='paused':break
                if self.stopped.wait(job.get('delay_seconds',.5)):job['state']='interrupted';break
            else:job['state']='completed'
        except PermissionError:job.update(state='paused',error='authorization_changed')
        except ConflictError:job.update(state='paused',error='workspace_changed')
        finally:
            try:self._save(root,job)
            except (OSError,ValueError,ConflictError):pass

    def stop(self):
        self.stopped.set()
        for thread in list(self.threads.values()):thread.join(timeout=2)
