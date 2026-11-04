import {useEffect, useMemo, useRef, useState} from 'react';
import {ChevronLeft, ChevronRight, List, Maximize2, Search} from 'lucide-react';
import {coursePages, courseTitle} from './course-pages';
import './course.css';

type StudioFrame = Window & {LeafLoomStudioInstance?: {navigate: (id: string) => void; fit: () => void}};

export default function App() {
  const frame = useRef<HTMLIFrameElement>(null);
  const [selected, setSelected] = useState(coursePages[0]?.id || '');
  const [filter, setFilter] = useState('');
  const [showList, setShowList] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const pages = useMemo(() => coursePages.filter(page => page.name.toLowerCase().includes(filter.trim().toLowerCase())), [filter]);
  const index = coursePages.findIndex(page => page.id === selected);
  const current = coursePages[index];
  const navigate = (id: string) => {
    const target = frame.current?.contentWindow as StudioFrame | null;
    if (!target?.LeafLoomStudioInstance) return;
    target.LeafLoomStudioInstance.navigate(id);
    setSelected(id);
  };
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow) return;
      if (event.data?.type === 'course-navigate' && coursePages.some(page => page.id === event.data.pageId)) setSelected(event.data.pageId);
    };
    window.addEventListener('message', receive);
    return () => window.removeEventListener('message', receive);
  }, []);
  return <div className="course-app">
    <header className="course-header">
      <div className="course-brand"><span className="course-mark">H</span><div><strong>{courseTitle}</strong><small>DESIGN STUDIO</small></div></div>
      <div className="course-toolbar"><span className="course-current">{current?.name}</span><button type="button" aria-label="上一页" disabled={!loaded || index <= 0} onClick={() => navigate(coursePages[index - 1].id)}><ChevronLeft size={19}/></button><span className="course-count">{index + 1} / {coursePages.length}</span><button type="button" aria-label="下一页" disabled={!loaded || index < 0 || index >= coursePages.length - 1} onClick={() => navigate(coursePages[index + 1].id)}><ChevronRight size={19}/></button><button type="button" aria-label="适应画面" title="适应画面" onClick={() => (frame.current?.contentWindow as StudioFrame | null)?.LeafLoomStudioInstance?.fit()}><Maximize2 size={17}/></button><button type="button" aria-label={showList ? '收起目录' : '显示目录'} title={showList ? '收起目录' : '显示目录'} onClick={() => setShowList(value => !value)}><List size={19}/></button></div>
    </header>
    <div className="course-body">
      {showList && <aside className="course-sidebar" aria-label="课程目录"><div className="course-sidebar-head"><strong>课程目录</strong><small>{coursePages.length} 页</small></div><label className="course-search"><Search size={16}/><input aria-label="搜索课程" placeholder="搜索课程主题" value={filter} onChange={event => setFilter(event.target.value)}/></label><nav className="course-list">{pages.map((page) => <button key={page.id} type="button" className={selected === page.id ? 'course-item active' : 'course-item'} onClick={() => navigate(page.id)} aria-current={selected === page.id ? 'page' : undefined}><span>{String(coursePages.indexOf(page) + 1).padStart(2,'0')}</span><strong>{page.name}</strong></button>)}{!pages.length && <p className="course-empty">没有找到匹配的课程</p>}</nav></aside>}
      <main className="course-stage"><iframe ref={frame} title={courseTitle} src={`${(process.env.CLIENT_BASE_PATH || '/').replace(/\/?$/, '/')}course.html`} onLoad={() => setLoaded(true)}/>{!loaded && <div className="course-loading">正在加载培训课件…</div>}</main>
    </div>
  </div>;
}
