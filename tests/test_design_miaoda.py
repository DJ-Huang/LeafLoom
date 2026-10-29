"""Miaoda publishing contracts without network writes or live credentials."""
import json
import subprocess
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests import test_design_workspace as fixture
from vault_rag.design_miaoda import MiaodaPublisher, _rewrite, _destination, _write, _remove_previous_text_assets, _tracked_files, _verify_association
from vault_rag.feishu import FeishuError
from vault_rag.local_state import ConflictError


class DeferredPool:
    def __init__(self): self.calls = []
    def submit(self, *args): self.calls.append(args)


class MiaodaTests(unittest.TestCase):
    setUp = fixture.DesignWorkspaceTests.setUp
    tearDown = fixture.DesignWorkspaceTests.tearDown
    create = fixture.DesignWorkspaceTests.create
    summary = fixture.DesignWorkspaceTests.summary

    def publisher(self):
        self.studio.workspace = self.workspace
        publisher = MiaodaPublisher(self.studio, SimpleNamespace(lock=threading.RLock()))
        publisher.pool = DeferredPool()
        return publisher

    def test_selection_target_and_revision_are_checked_before_work(self):
        publisher = self.publisher(); page = self.project['document']['pages'][0]['id']
        body = {'directory': self.directory, 'expected_revision': self.project['revision'], 'page_ids': [page], 'target': {'type':'existing','app_id':'app_notlinked'}}
        with self.assertRaisesRegex(ValueError, 'Associate'):
            publisher.start(body)
        with self.assertRaises(ConflictError):
            publisher.start({**body, 'expected_revision':'stale'})
        with self.assertRaisesRegex(ValueError, 'Select at least one'):
            publisher.start({**body, 'page_ids':[]})
        job = publisher.start({**body, 'target':{'type':'new','name':'Course'}})
        self.assertEqual(job['status'], 'queued')
        self.assertEqual(job['page_ids'], [page])
        self.assertEqual(len(publisher.pool.calls), 1)

    def test_publication_snapshot_does_not_write_to_the_project(self):
        project = self.root/self.directory
        def state():
            return {path.relative_to(project).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
                    for path in project.rglob('*') if path.is_file()}
        before = state()
        result = self.workspace.export(self.directory, [self.project['document']['pages'][0]['id']],
                                       self.project['revision'], snapshot_dir=self.root/'private-snapshot')
        self.assertTrue(Path(result['snapshot_path']).is_file())
        self.assertEqual(state(), before)

    def test_cli_adapter_passes_stdout_and_stderr_to_result_validation(self):
        publisher = self.publisher()
        publisher.feishu._ready = lambda: None
        publisher.feishu._run = lambda *args, **kwargs: (0, 'output', 'diagnostic')
        observed = []
        def result(code, out, err, **kwargs):
            observed.append((code, out, err))
            return {'ok': True, 'data': {'ok': True, 'identity': 'user', 'data': {'items': []}}}
        publisher.feishu._result = result
        self.assertEqual(publisher._cli(['apps', '+list']), {'items': []})
        self.assertEqual(observed, [(0, 'output', 'diagnostic')])
        publisher.feishu._result = lambda *args, **kwargs: {'ok': False, 'error_code': 'permission_denied', 'error': 'Permission denied', 'missing_scopes': ['spark:app:write']}
        with self.assertRaises(FeishuError) as failure:
            publisher._cli(['apps', '+list'])
        self.assertEqual(failure.exception.code, 'permission_denied')
        self.assertEqual(failure.exception.details['missing_scopes'], ['spark:app:write'])

    def test_association_validates_frontend_and_managed_layout(self):
        publisher = self.publisher()
        with patch.object(publisher, '_cli', return_value={'app': {'app_type':'full_stack'}}):
            with self.assertRaisesRegex(ValueError, 'frontend'):
                publisher.associate(self.directory, 'app_bad')
        def clone(app, repo):
            (repo/'src').mkdir(parents=True); (repo/'public').mkdir()
            (repo/'src/app.tsx').write_text('LeafLoomStudioInstance')
            (repo/'public/course-data.js').write_text('window.STUDIO_DOCUMENT='+json.dumps({'id':self.project['document']['id']})+';')
            (repo/'public/course.html').write_text('')
            (repo/'public/course-runtime.js').write_text('')
            return 'verified-head'
        with patch.object(publisher, '_cli', return_value={'app': {'app_type':'frontend','name':'Training'}}), patch.object(publisher, '_clone', side_effect=clone), patch('vault_rag.design_miaoda._verify_association'):
            result = publisher.associate(self.directory, 'app_course')
        self.assertEqual(result['app']['head'], 'verified-head')
        self.assertEqual(publisher.applications(self.directory)['apps'][0]['app_id'], 'app_course')
        def changed(app, repo):
            clone(app, repo)
            return 'changed-head'
        with patch.object(publisher, '_cli', return_value={'app': {'app_type':'frontend','name':'Training'}}), patch.object(publisher, '_clone', side_effect=changed):
            with self.assertRaises(ConflictError):
                publisher.associate(self.directory, 'app_course')
        self.assertEqual(publisher.applications(self.directory)['apps'][0]['head'], 'verified-head')

    def test_association_refuses_unrecognized_remote_code(self):
        repo=self.root/'git-course';repo.mkdir()
        def git(*args):
            return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True).stdout
        git('init'); (repo/'src').mkdir(); (repo/'public').mkdir()
        (repo/'src/app.tsx').write_text('recognized')
        (repo/'skills-link').symlink_to('src', target_is_directory=True)
        git('add','src/app.tsx','skills-link')
        _write(repo/'public/leafloom-course.json', {'version':2,'project_id':'course','tracked_files':_tracked_files(repo)})
        git('add','public/leafloom-course.json')
        _verify_association(repo, 'unknown-head', 'course')
        (repo/'src/app.tsx').write_text('changed by someone else')
        git('add','src/app.tsx')
        with self.assertRaises(ConflictError):
            _verify_association(repo, 'unknown-head', 'course')

    def test_retry_refuses_unverified_upload_and_recovers_unique_result(self):
        publisher = self.publisher(); jobid = 'a'*32
        job = {'job_id':jobid,'root':str(self.config.root),'directory':self.directory,'status':'interrupted','stage':'failed','last_stage':'upload_assets','app_id':'app_course','pending_asset':'abc.png'}
        publisher._save_job(job)
        with patch.object(publisher, '_cli', return_value={'items':[], 'has_more':False}):
            with self.assertRaisesRegex(ValueError, 'uniquely confirmed'):
                publisher.retry(jobid)
        self.assertEqual(publisher.get(jobid)['status'], 'interrupted')
        with patch.object(publisher, '_cli', return_value={'items':[{'file_name':'abc.png','download_url':'/spark/app/app_course/object'}], 'has_more':False}):
            result=publisher.retry(jobid)
        self.assertEqual(result['status'], 'queued')
        self.assertTrue(result['resume'])
        self.assertEqual(publisher._load('assets-app_course.json', {})['abc.png'], '/spark/app/app_course/object')

    def test_release_stops_for_approval_and_only_finished_has_url(self):
        publisher = self.publisher(); jobid='b'*32
        job={'job_id':jobid,'root':str(self.config.root),'directory':self.directory,'status':'release_pending','stage':'release_pending','app_id':'app_course','release_id':'1','target':{'type':'existing'}}
        publisher._save_job(job)
        with patch.object(publisher, '_cli', return_value={'status':'publishing','online_url':'https://early.invalid','current_node_info':{'current_status':'PENDING','result':{'approval_url':'https://example.com/review'}}}):
            value=publisher.refresh(jobid)
        self.assertEqual(value['status'],'awaiting_approval');self.assertNotIn('url',value)
        with patch.object(publisher, '_cli', return_value={'status':'finished','online_url':'https://example.com/course'}):
            value=publisher.refresh(jobid)
        self.assertEqual(value['status'],'completed');self.assertEqual(value['url'],'https://example.com/course')

    def test_new_app_confirms_company_access_after_first_release(self):
        publisher = self.publisher(); jobid = 'c'*32
        job={'job_id':jobid,'root':str(self.config.root),'directory':self.directory,'status':'release_pending','stage':'release_pending','app_id':'app_course','release_id':'1','target':{'type':'new'}}
        publisher._save_job(job)
        calls = []
        def cli(args):
            calls.append(args[1])
            if args[1] == '+release-get': return {'status':'finished','online_url':'https://example.com/course'}
            if args[1] == '+access-scope-get': return {'scope': 'Tenant' if '+access-scope-set' in calls else 'Range'}
            return {}
        with patch.object(publisher, '_cli', side_effect=cli):
            value = publisher.refresh(jobid)
        self.assertEqual(calls, ['+release-get', '+access-scope-get', '+access-scope-set', '+access-scope-get'])
        self.assertEqual(value['status'], 'completed')
        self.assertTrue(value['access_confirmed'])

    def test_new_app_access_failure_is_not_reported_as_complete(self):
        publisher = self.publisher(); jobid = 'd'*32
        job={'job_id':jobid,'root':str(self.config.root),'directory':self.directory,'status':'release_pending','stage':'release_pending','app_id':'app_course','release_id':'1','target':{'type':'new'}}
        publisher._save_job(job)
        def cli(args):
            if args[1] == '+release-get': return {'status':'finished','online_url':'https://example.com/course'}
            raise FeishuError('login_expired', 'Login expired')
        with patch.object(publisher, '_cli', side_effect=cli):
            value = publisher.refresh(jobid)
        self.assertEqual(value['status'], 'release_unknown')
        self.assertEqual(value['error_code'], 'login_expired')
        self.assertNotIn('url', value)

    def test_new_app_does_not_report_success_if_access_changed(self):
        publisher = self.publisher(); jobid = '9'*32
        job={'job_id':jobid,'root':str(self.config.root),'directory':self.directory,'status':'release_pending','stage':'release_pending','app_id':'app_course','release_id':'1','target':{'type':'new'},'release_kind':'course','access_confirmed':True}
        publisher._save_job(job)
        calls=[]
        def cli(args):
            calls.append(args[1])
            return {'status':'finished','online_url':'https://example.com/course'} if args[1]=='+release-get' else {'scope':'Public'}
        with patch.object(publisher, '_cli', side_effect=cli):
            value=publisher.refresh(jobid)
        self.assertEqual(value['status'], 'release_unknown')
        self.assertNotIn('url', value)
        self.assertEqual(calls, ['+release-get','+access-scope-get'])

    def test_bootstrap_waits_for_access_before_resuming_course(self):
        publisher = self.publisher(); jobid = 'e'*32
        job={'job_id':jobid,'root':str(self.config.root),'directory':self.directory,'status':'release_pending','stage':'release_pending','app_id':'app_course','release_id':'empty-release','release_kind':'bootstrap','target':{'type':'new'}}
        publisher._save_job(job)
        def cli(args):
            if args[1] == '+release-get': return {'status':'finished'}
            if args[1] == '+access-scope-get': return {'scope':'Tenant'}
            self.fail('Course content must not be uploaded before access is confirmed')
        with patch.object(publisher, '_cli', side_effect=cli):
            value = publisher.refresh(jobid)
        self.assertEqual(value['status'], 'queued')
        self.assertEqual(value['release_kind'], 'course')
        self.assertEqual(value['bootstrap_release_id'], 'empty-release')
        self.assertTrue(value['access_confirmed'])
        self.assertTrue(value['resume'])
        self.assertEqual(len(publisher.pool.calls), 1)

    def test_rewrites_resources_and_rejects_checkout_symlinks(self):
        path='Design/Assets/a.png'; urls={path:'/spark/app/app_course/object'}
        result=_rewrite({'src':'__STUDIO_ASSET__/'+path,'css':'url(../Assets/a.png)'},urls,'Design/styles/page.css')
        self.assertEqual(result['src'],urls[path]);self.assertIn(urls[path],result['css'])
        text = 'url(Design/Assets/a.png) url(Design/Assets/a.png2) https://other.example/Design/Assets/a.png'
        self.assertEqual(_rewrite(text, urls), 'url(/spark/app/app_course/object) url(Design/Assets/a.png2) https://other.example/Design/Assets/a.png')
        repo=self.root/'repo';repo.mkdir();(repo/'public').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symbolic link'):
            _destination(repo,'public/course.html')

    def test_replacement_removes_only_recorded_previous_text_assets(self):
        repo = self.root/'checkout'; public = repo/'public'; public.mkdir(parents=True)
        (public/'old.js').write_text('old'); (public/'unrelated.js').write_text('keep')
        _write(public/'leafloom-course.json', {'project_id':'course', 'generated_assets':['old.js']})
        _remove_previous_text_assets(repo, 'course')
        self.assertFalse((public/'old.js').exists())
        self.assertTrue((public/'unrelated.js').exists())
        _write(public/'leafloom-course.json', {'project_id':'course', 'generated_assets':['../unrelated.js']})
        with self.assertRaises(ValueError):
            _remove_previous_text_assets(repo, 'course')

    def test_background_advances_initial_release_without_dialog(self):
        publisher = self.publisher(); jobid = 'f'*32
        job={'job_id':jobid,'root':str(self.config.root),'directory':self.directory,'status':'queued','stage':'queued','target':{'type':'new'}}
        publisher._save_job(job); publisher.active.add(jobid)
        calls = []
        def publish(current):
            calls.append(current.get('release_kind', 'initial'))
            if len(calls) == 1:
                current.update(status='release_pending', release_id='initial-id', release_kind='bootstrap')
            else:
                self.assertTrue(current['access_confirmed'])
                current.update(status='completed', stage='completed')
        def release(current):
            current.update(stage='bootstrap_ready', access_confirmed=True)
        with patch.object(publisher, '_publish', side_effect=publish), patch.object(publisher, '_release_status', side_effect=release), patch('vault_rag.design_miaoda.time.sleep'):
            publisher._run(jobid)
        self.assertEqual(calls, ['initial', 'course'])
        self.assertNotIn(jobid, publisher.active)

    def test_complete_publication_reuses_identical_media(self):
        publisher=self.publisher(); page=self.project['document']['pages'][0]
        export=self.root/'course.zip'
        doc={'id':self.project['document']['id'],'name':'Course','pages':[{'id':page['id'],'name':'First','nodes':[]}], 'assets':{},'scripts':{},'components':{},'styles':{}}
        with zipfile.ZipFile(export,'w') as z:
            z.writestr('document.js','window.STUDIO_DOCUMENT='+json.dumps(doc)+';')
            z.writestr('Design/Assets/a.png',b'same')
            z.writestr('Design/Assets/b.png',b'same')
        app_id='app_course';jobid='c'*32
        _write(publisher._state('applications.json'),{'apps':{app_id:{'app_id':app_id,'directory':self.directory,'name':'Course','head':'old'}}})
        job={'job_id':jobid,'root':str(self.config.root),'directory':self.directory,'revision':self.project['revision'],'page_ids':[page['id']], 'target':{'type':'existing','app_id':app_id},'app_id':app_id,'reason':'course','status':'running','stage':'queued','completed':0,'total':0}
        def clone(_,repo):
            (repo/'src').mkdir(parents=True);(repo/'public').mkdir()
            (repo/'src/app.tsx').write_text('LeafLoomStudioInstance')
            (repo/'public/course-data.js').write_text('window.STUDIO_DOCUMENT='+json.dumps({'id':doc['id']})+';')
            (repo/'public/course.html').write_text('')
            (repo/'public/course-runtime.js').write_text('')
            return 'old'
        calls=[]
        def cli(args, **kwargs):
            calls.append(args)
            if '+file-upload' in args: return {'download_url':'/spark/app/app_course/object/1.png'}
            if '+release-create' in args:return {'release_id':'release1'}
            if '+release-get' in args:return {'status':'finished','online_url':'https://example.com/course'}
            raise AssertionError(args)
        def git(repo,*args,**kwargs):
            if args[0]=='ls-remote':return 'old refs/heads/sprint/default'
            if args[0]=='status':return 'M file'
            if args[0]=='rev-parse':return 'new'
            return ''
        with patch.object(self.workspace,'export',return_value={'snapshot_path':str(export)}),patch.object(publisher,'_clone',side_effect=clone),patch.object(publisher,'_cli',side_effect=cli),patch('vault_rag.design_miaoda._git',side_effect=git),patch('vault_rag.design_miaoda._verify_association'):
            publisher._publish(job)
        self.assertEqual(sum('+file-upload' in c for c in calls),1)
        self.assertEqual(job['status'],'completed');self.assertEqual(publisher._apps()['apps'][app_id]['head'],'new')

    def test_remote_change_stops_before_upload_or_push(self):
        publisher=self.publisher();page=self.project['document']['pages'][0]
        export=self.root/'conflict.zip'
        doc={'id':self.project['document']['id'],'name':'Course','pages':[{'id':page['id'],'name':'First','nodes':[]}], 'assets':{},'scripts':{},'components':{},'styles':{}}
        with zipfile.ZipFile(export,'w') as z:
            z.writestr('document.js','window.STUDIO_DOCUMENT='+json.dumps(doc)+';')
            z.writestr('Design/Assets/a.png',b'image')
        app_id='app_course';jobid='d'*32
        _write(publisher._state('applications.json'),{'apps':{app_id:{'app_id':app_id,'directory':self.directory,'name':'Course','head':'old'}}})
        job={'job_id':jobid,'root':str(self.config.root),'directory':self.directory,'revision':self.project['revision'],'page_ids':[page['id']], 'target':{'type':'existing','app_id':app_id},'app_id':app_id,'reason':'course','status':'running','stage':'queued','completed':0,'total':0}
        def clone(_,repo):
            (repo/'src').mkdir(parents=True);(repo/'public').mkdir()
            (repo/'src/app.tsx').write_text('LeafLoomStudioInstance')
            (repo/'public/course-data.js').write_text('window.STUDIO_DOCUMENT='+json.dumps({'id':doc['id']})+';')
            (repo/'public/course.html').write_text('');(repo/'public/course-runtime.js').write_text('')
            return 'changed'
        with patch.object(self.workspace,'export',return_value={'snapshot_path':str(export)}),patch.object(publisher,'_clone',side_effect=clone),patch.object(publisher,'_cli') as cli:
            with self.assertRaises(ConflictError):publisher._publish(job)
            cli.assert_not_called()

class MiaodaRouteTests(unittest.TestCase):
    setUp = __import__('tests.test_design_studio', fromlist=['DesignStudioTests']).DesignStudioTests.setUp
    tearDown = __import__('tests.test_design_studio', fromlist=['DesignStudioTests']).DesignStudioTests.tearDown

    def test_miaoda_routes_validate_scope_and_selection(self):
        routes = [(method, route.path) for route in self.app.routes
                  if getattr(route, 'path', '').startswith('/api/design/')
                  for method in getattr(route, 'methods', [])]
        self.assertEqual(len(routes), len(set(routes)), 'Design endpoints must be registered only once')
        created = self.client.post('/api/design/projects', headers=self.auth, json={
            'root': str(self.root), 'directory': 'Projects/Miaoda', 'name': 'Course', 'managed': True})
        self.assertEqual(created.status_code, 200, created.text)
        body = created.json()
        page_id = body['document']['pages'][0]['id']
        apps = self.client.get('/api/design/miaoda/apps', headers=self.auth,
                               params={'root':str(self.root),'directory':'Projects/Miaoda'})
        self.assertEqual(apps.status_code, 200); self.assertEqual(apps.json()['apps'], [])
        payload={'root':str(self.root),'directory':'Projects/Miaoda','expected_revision':body['revision'],
                 'page_ids':[],'target':{'type':'new','name':'Course'}}
        response=self.client.post('/api/design/miaoda/publish',headers=self.auth,json=payload)
        self.assertEqual(response.status_code,400,response.text)
        payload['page_ids']=[page_id];payload['root']='/wrong-root'
        response=self.client.post('/api/design/miaoda/publish',headers=self.auth,json=payload)
        self.assertEqual(response.status_code,409,response.text)

if __name__ == "__main__":
    unittest.main()
