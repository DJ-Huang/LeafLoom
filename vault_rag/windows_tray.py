"""Notification-area controls, independent of the model/server process."""
from __future__ import annotations
import logging
import os
import threading
from vault_rag.platform_support import show_error
from vault_rag.service_control import control, request, health
from vault_rag.windows_native import Instance
from vault_rag.windows_service import autostart_enabled


def tray_image(state):
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (64,64))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((3,3,61,61), radius=12, fill='#315e4b')
    draw.polygon([(32,16),(13,12),(13,47),(32,52),(51,47),(51,12)], fill='#faf7e9')
    draw.line((32,16,32,51), fill='#73927c', width=2)
    colors = {'ready':'#65bc75', 'stopped':'#9caaa3', 'error':'#e4a348'}
    draw.ellipse((43,43,62,62), fill=colors.get(state,'#9caaa3'), outline='#315e4b', width=2)
    return image


class TrayController:
    def __init__(self, config):
        self.config=config; self.stop=threading.Event(); self.busy=threading.Lock()
        self.state='stopped'; self.summary='正在检查服务'; self.detail=''
        self.autostart=autostart_enabled(config); self.icon=None

    def refresh(self):
        try:
            state=health(self.config)
            if state=='ready':
                data=request('/api/status', config=self.config, timeout=3)
                error=data.get('last_error') or data.get('model',{}).get('error')
                self.state='error' if error else 'ready'; self.summary='服务运行中 · HTTP MCP'
                self.detail=('错误：'+str(error)) if error else (
                    f"{data.get('num_files',0)} 篇 · {data.get('sync',{}).get('state','检查中')} · " +
                    ('模型已加载' if data.get('model',{}).get('loaded') else '模型未加载'))
            else:
                self.state='error' if state=='other' else 'stopped'
                self.summary='端口被其他程序占用' if state=='other' else '服务未响应 / 已停止'
                self.detail='点击启动服务恢复'
        except Exception as error:
            self.state='error'; self.summary='状态查询失败'; self.detail=str(error)
        if self.icon:
            self.icon.icon=tray_image(self.state)
            self.icon.title=('本地知识库：'+self.summary+'\n'+self.detail)[:120]
            self.icon.update_menu()

    def action(self, action):
        if not self.busy.acquire(blocking=False):return
        def work():
            try:
                if action=='refresh':self.refresh()
                elif action=='logs':os.startfile(str(self.config.directory/'logs'))
                elif action=='exit':
                    control('stop',self.config)
                    self.quit()
                else:
                    control(action,self.config)
                    if action.endswith('autostart'):self.autostart=action=='enable-autostart'
            except Exception as error:
                logging.exception('Tray action failed: %s',action)
                show_error(str(error)+'\n日志：'+str(self.config.directory/'logs'))
            finally:
                self.busy.release()
                if not self.stop.is_set():self.refresh()
        threading.Thread(target=work,daemon=True).start()

    def quit(self):
        self.stop.set();self.icon.stop()


def run(config):
    import pystray
    with Instance(config.directory,'tray') as instance:
        if not instance.primary:return
        controller=TrayController(config)
        item=pystray.MenuItem
        def invoke(action):return lambda icon,entry:controller.action(action)
        menu=pystray.Menu(
            item(lambda entry:controller.summary,None,enabled=False),
            item(lambda entry:controller.detail,None,enabled=False), pystray.Menu.SEPARATOR,
            item('打开网页',invoke('open'),default=True), item('刷新状态',invoke('refresh')),
            pystray.Menu.SEPARATOR,
            *[item(label,invoke(action),enabled=lambda entry:not controller.busy.locked())
              for label,action in [('启动服务','start'),('停止服务','stop'),('重启服务','restart')]],
            pystray.Menu.SEPARATOR,
            item('查看日志',invoke('logs')),
            item(lambda entry:'取消登录启动' if controller.autostart else '恢复登录启动',
                 lambda icon,entry:controller.action('disable-autostart' if controller.autostart else 'enable-autostart')),
            item('退出',invoke('exit'),enabled=lambda entry:not controller.busy.locked()),
        )
        icon=pystray.Icon('vault-rag',tray_image('stopped'),'本地知识库',menu)
        controller.icon=icon
        poll_thread=None
        def poll():
            while not controller.stop.is_set():
                if not controller.busy.locked():controller.refresh()
                controller.stop.wait(5)
        def watch_stop():
            # Shutdown must work even if a status refresh is blocked or failed.
            while not controller.stop.is_set():
                if instance.wait_for_stop(200):controller.quit();return
        def setup(icon):
            nonlocal poll_thread
            if controller.stop.is_set():icon.stop();return
            icon.visible=True
            poll_thread=threading.Thread(target=poll,daemon=True);poll_thread.start()
        stop_thread=threading.Thread(target=watch_stop,daemon=True);stop_thread.start()
        try:icon.run(setup)
        finally:
            controller.stop.set()
            stop_thread.join()
            # This worker only reads status; it must not hold the icon alive.
            if poll_thread:poll_thread.join(timeout=5)
