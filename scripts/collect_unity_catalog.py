#!/usr/bin/env python3
"""Start/observe LeafLoom's local collector; never fetch websites or packages."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import time
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlencode,urlsplit,urlunsplit
from urllib.request import HTTPRedirectHandler,ProxyHandler,Request,build_opener


MAX_RESPONSE_BYTES=16*1024*1024
MAX_CHINESE_BYTES=32*1024*1024
CHINESE_FIELDS={'summary_zh','summary_status','categories_zh','keywords_zh','url'}
TERMINAL={'completed','paused','interrupted','failed','idle'}


class CollectionError(Exception):
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)


def api_origin(value):
    """Validate before loading a credential or constructing an authenticated request."""
    try:
        if not isinstance(value,str) or any(ord(char)<=32 or ord(char)==127 for char in value) or '?' in value or '#' in value:raise ValueError()
        parsed=urlsplit(value)
        if (parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.username is not None or
                parsed.password is not None or parsed.path or parsed.query or parsed.fragment):raise ValueError()
        address=ipaddress.ip_address(parsed.hostname or '')
        if not address.is_loopback or '%' in str(address):raise ValueError()
        port=parsed.port
        if port is not None and not 1<=port<=65535 or parsed.netloc.endswith(':'):raise ValueError()
        host='['+address.compressed+']' if address.version==6 else address.compressed
        return urlunsplit((parsed.scheme,host+(':'+str(port) if port is not None else ''),'','',''))
    except (TypeError,ValueError):
        raise CollectionError('invalid_api_origin','Use a bare HTTP(S) origin with a literal loopback IP; paths, credentials and redirects are forbidden.') from None


def default_token_file():
    if os.environ.get('VAULT_RAG_HOME'):return Path(os.environ['VAULT_RAG_HOME']).expanduser()/'auth-token'
    if sys.platform=='win32':
        base=Path(os.environ['LOCALAPPDATA']) if os.environ.get('LOCALAPPDATA') else Path.home()/'AppData/Local'
    elif sys.platform=='darwin':base=Path.home()/'Library/Application Support'
    else:base=Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))
    return base/'VaultRag/auth-token'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,message,headers,newurl):
        raise CollectionError('local_api_redirect_refused','The local API redirected the request; no credential was forwarded.')


class LocalAPI:
    def __init__(self,origin,token,timeout=30):
        self.origin=api_origin(origin);self.token=token;self.timeout=timeout
        self.opener=build_opener(ProxyHandler({}),NoRedirect())

    def request(self,method,path,body=None):
        if not path.startswith('/api/') or path.startswith('//'):raise CollectionError('invalid_api_path','Invalid local API request.')
        headers={'Authorization':'Bearer '+self.token,'Accept':'application/json'}
        data=None
        if body is not None:
            headers['Content-Type']='application/json'
            data=json.dumps(body,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
        request=Request(self.origin+path,data=data,headers=headers,method=method)
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                if not 200<=response.status<300:raise CollectionError('local_api_http_'+str(response.status),'The local API returned HTTP '+str(response.status)+'.')
                media=response.headers.get('Content-Type','').split(';')[0].strip().lower()
                if media!='application/json' and not (media.startswith('application/') and media.endswith('+json')):
                    raise CollectionError('local_api_non_json','The local API returned HTML or another non-JSON response.')
                raw=response.read(MAX_RESPONSE_BYTES+1)
                if len(raw)>MAX_RESPONSE_BYTES:raise CollectionError('local_api_response_too_large','The local API response exceeded its size limit.')
        except HTTPError as error:
            raise CollectionError('local_api_http_'+str(error.code),'The local API returned HTTP '+str(error.code)+'; check authentication and service status.') from None
        except (TimeoutError,socket.timeout):
            raise CollectionError('local_api_timeout','The local API timed out. A task already started may continue; use --status to check it.') from None
        except URLError as error:
            if isinstance(error.reason,(TimeoutError,socket.timeout)):
                raise CollectionError('local_api_timeout','The local API timed out. A task already started may continue; use --status to check it.') from None
            raise CollectionError('local_api_unavailable','Cannot reach the local LeafLoom API; start LeafLoom and check its port.') from None
        except OSError:
            raise CollectionError('local_api_unavailable','The connection to the local LeafLoom API was interrupted; use --status before retrying.') from None
        try:
            result=json.loads(raw,parse_constant=lambda value:(_ for _ in ()).throw(ValueError()))
        except (ValueError,UnicodeError):raise CollectionError('local_api_invalid_json','The local API returned invalid JSON.') from None
        if not isinstance(result,dict):raise CollectionError('local_api_invalid_json','The local API returned an unexpected JSON value.')
        return result

    def status(self,root):return self.request('GET','/api/asset-library/status?'+urlencode({'root':root}))


def _code(value,limit=200):
    return value if isinstance(value,str) and len(value)<=limit and re.fullmatch(r'[A-Za-z0-9_.:-]*',value) else ''


def redacted_job(value):
    if not isinstance(value,dict) or value.get('state') not in TERMINAL|{'running','queued'}:
        raise CollectionError('invalid_collection_status','The local API returned an invalid collection status.')
    result={key:_code(value[key]) for key in ('job_id','state','error') if key in value}
    result.update({key:value[key] for key in ('total','succeeded','needs_review','failed','legacy_unresolved') if type(value.get(key))is int and value[key]>=0})
    result['results']=[]
    for item in value.get('results',[]):
        if isinstance(item,dict):result['results'].append({key:_code(item[key]) for key in ('id','state','reason','product_id') if key in item})
    return result


def atomic_report(path,value):
    path=Path(path).expanduser();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.'+path.name+'.',delete=False) as stream:
            temporary=Path(stream.name);os.chmod(temporary,0o600)
            json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def chinese_entries(path):
    try:
        with Path(path).expanduser().open('rb') as stream:raw=stream.read(MAX_CHINESE_BYTES+1)
        if len(raw)>MAX_CHINESE_BYTES:raise ValueError()
        entries=json.loads(raw,parse_constant=lambda value:(_ for _ in ()).throw(ValueError()))
        if not isinstance(entries,list) or len(entries)>20000:raise ValueError()
        checked=[];seen=set()
        for entry in entries:
            if not isinstance(entry,dict) or not {'product_id','official'}<=set(entry) or set(entry)-{'product_id','official','expected_revision'}:raise ValueError()
            product=str(entry['product_id']).removeprefix('unity.assetstore:')
            if not re.fullmatch(r'[1-9][0-9]{0,17}',product) or product in seen:raise ValueError()
            official=entry['official']
            if not isinstance(official,dict) or not official or set(official)-CHINESE_FIELDS:raise ValueError()
            official=dict(official)
            for key,value in official.items():
                if key in {'categories_zh','keywords_zh'}:
                    if not isinstance(value,list) or len(value)>100 or any(not isinstance(text,str) or len(text)>200 or '\x00' in text for text in value):raise ValueError()
                    official[key]=list(dict.fromkeys(value))
                elif not isinstance(value,str) or '\x00' in value or len(value)>({'summary_zh':10000,'summary_status':500,'url':4096}[key]):raise ValueError()
                if key=='url':
                    url=urlsplit(value)
                    match=re.search(r'(?:-|/)([1-9][0-9]*)/?$',url.path)
                    if (url.scheme!='https' or url.hostname!='assetstore.unity.com' or url.port not in {None,443} or
                            url.username is not None or url.password is not None or url.query or url.fragment or not match or match[1]!=product):raise ValueError()
            expected=entry.get('expected_revision','')
            if not isinstance(expected,str) or expected and not re.fullmatch('[0-9a-f]{64}',expected):raise ValueError()
            checked.append({'product_id':product,'official':official,'expected_revision':expected});seen.add(product)
        return checked
    except (OSError,ValueError,TypeError,UnicodeError):
        raise CollectionError('invalid_chinese_input','Use a JSON array of unique product_id/official entries containing only the allowed Chinese fields and matching official URL.') from None


def chinese_operation_id(product,official,revision):
    # The backend receipt also fingerprints the expected revision. Include that
    # baseline so a later, deliberate reapplication cannot collide with it.
    content=json.dumps([product,official,revision],ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return 'collect-unity-chinese:'+hashlib.sha256(content).hexdigest()


def apply_chinese(api,root,entries,report,publish):
    report.update(mode='apply_chinese',state='running',total=len(entries),applied=0,unchanged=0,results=[])
    publish(report)
    for entry in entries:
        product=entry['product_id'];official=entry['official']
        report['active_product_id']=product
        current=api.request('GET','/api/asset-library/products/'+quote(product,safe='')+'?'+urlencode({'root':root}))
        revision=current.get('revision','')
        if (str(current.get('product_id',''))!=product or not isinstance(current.get('official'),dict) or
                not isinstance(revision,str) or not re.fullmatch('[0-9a-f]{64}',revision)):
            raise CollectionError('invalid_product_detail','The local API returned an invalid product identity or revision.')
        if all(current['official'].get(key)==value for key,value in official.items()):state='unchanged'
        else:
            if entry.get('expected_revision') and entry['expected_revision']!=revision:
                raise CollectionError('product_revision_changed','Product facts changed since this input was prepared; refresh its Chinese metadata before retrying.')
            updated=api.request('POST','/api/asset-library/actions',{'root':root,'action':'official','product_id':product,'official':official,
                'expected_revision':revision,'operation_id':chinese_operation_id(product,official,revision)})
            revision=updated.get('revision','')
            if (str(updated.get('product_id',''))!=product or not isinstance(revision,str) or not re.fullmatch('[0-9a-f]{64}',revision) or
                    not isinstance(updated.get('official'),dict) or any(updated['official'].get(key)!=value for key,value in official.items())):
                raise CollectionError('invalid_product_detail','The local API did not confirm the expected partial metadata update.')
            state='applied'
        report[state]+=1;report['results'].append({'product_id':product,'state':state,'revision':revision});publish(report)
    report.pop('active_product_id',None);report['state']='completed';publish(report)


def parser():
    result=argparse.ArgumentParser(description=__doc__,epilog='Stopping this monitor does not cancel the backend task. No website parsing or package downloads run in this script.')
    result.add_argument('--root',required=True,help='The folder currently connected to LeafLoom.')
    result.add_argument('--api-url',default='http://127.0.0.1:18080',help='Bare loopback IP origin; no path or trailing slash.')
    result.add_argument('--token-file',type=Path,default=default_token_file(),help='Local private API token file; never written to reports.')
    mode=result.add_mutually_exclusive_group()
    mode.add_argument('--start',action='store_true',help='Start/resume the backend enrichment task.')
    mode.add_argument('--status',action='store_true',help='Read current collection status (the default).')
    mode.add_argument('--apply-chinese',type=Path,metavar='FILE',help='Apply validated partial Chinese metadata serially.')
    result.add_argument('--wait',action='store_true',help='Poll collection status until completed, paused, interrupted or failed.')
    result.add_argument('--interval',type=float,default=10,help='Polling seconds, from 1 through 60 (default: 10).')
    result.add_argument('--report',type=Path,help='Atomically save redacted JSON results and summary (mode 0600).')
    return result


def main(argv=None):
    arguments=parser().parse_args(argv);report={};report_path=None
    def publish(value):
        if report_path:atomic_report(report_path,value)
        summary={key:value[key] for key in ('mode','state','total','succeeded','needs_review','failed','applied','unchanged') if key in value}
        if 'job' in value:summary.update({key:item for key,item in value['job'].items() if key!='results'})
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    try:
        origin=api_origin(arguments.api_url)
        if not 1<=arguments.interval<=60:raise CollectionError('invalid_interval','Use --interval between 1 and 60 seconds.')
        if arguments.apply_chinese and arguments.wait:raise CollectionError('invalid_mode','--wait tracks collection; do not combine it with --apply-chinese.')
        root=str(Path(arguments.root).expanduser().resolve())
        token_path=arguments.token_file.expanduser()
        if arguments.report and (arguments.report.expanduser().resolve()==token_path.resolve() or
                arguments.apply_chinese and arguments.report.expanduser().resolve()==arguments.apply_chinese.expanduser().resolve()):
            raise CollectionError('invalid_report_path','The report must not replace the credential or Chinese input file.')
        report_path=arguments.report
        entries=chinese_entries(arguments.apply_chinese) if arguments.apply_chinese else None
        try:
            with token_path.open('rb') as stream:raw=stream.read(4097)
            token=raw.decode('ascii').strip()
            if len(raw)>4096 or not re.fullmatch('[A-Za-z0-9_.~-]+',token):raise ValueError()
        except (OSError,UnicodeError,ValueError):raise CollectionError('local_token_unavailable','Cannot read a valid local API token; check --token-file and start LeafLoom.') from None
        api=LocalAPI(origin,token)
        if entries is not None:
            apply_chinese(api,root,entries,report,publish);return 0
        job=api.request('POST','/api/asset-library/actions',{'root':root,'action':'enrich'}) if arguments.start else api.status(root).get('enrichment')
        while True:
            report.update(mode='collection',job=redacted_job(job));publish(report)
            if not arguments.wait:return 0
            if report['job']['state'] in TERMINAL:
                return 1 if report['job']['state']=='failed' else 2 if report['job']['state'] in {'paused','interrupted'} else 0
            time.sleep(arguments.interval);job=api.status(root).get('enrichment')
    except KeyboardInterrupt:
        report['monitoring']={'state':'stopped','code':'monitor_interrupted'}
        if report_path:
            try:atomic_report(report_path,report)
            except OSError:pass
        print('Monitoring stopped. Any backend collection task continues.',file=sys.stderr);return 130
    except CollectionError as error:
        report['cli_error']={'code':error.code}
        if report.get('mode')=='apply_chinese':report['state']='failed'
        if report_path:
            try:atomic_report(report_path,report)
            except OSError:pass
        print(error.code+': '+str(error),file=sys.stderr);return 1
    except OSError:
        print('local_file_error: Cannot access the requested input or report file.',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
