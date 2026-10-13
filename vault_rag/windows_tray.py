"""Notification-area controls, independent of the model/server process."""
from __future__ import annotations
import logging
import os
import threading
from vault_rag.platform_support import show_error
from vault_rag.service_control import control, request, health
from vault_rag.windows_native import Instance
from vault_rag.windows_service import autostart_enabled
from vault_rag.i18n import t
from pathlib import Path


def tray_image(state):
    from PIL import Image, ImageDraw
    brand = Path(__file__).parent/'brand/logo.png'
    if not brand.exists(): brand = Path(__file__).resolve().parents[1]/'assets/brand/logo.png'
    image = Image.open(brand).convert('RGBA').resize((64,64), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
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
                    f"{data.get('num_files',0)} "+t('篇',self.config.directory)+' · '+t(data.get('sync',{}).get('state','检查中'),self.config.directory)+' · ' +
                    t('模型已加载' if data.get('model',{}).get('loaded') else '模型未加载',self.config.directory))
            else:
                self.state='error' if state=='other' else 'stopped'
                self.summary='端口被其他程序占用' if state=='other' else '服务未响应 / 已停止'
                self.detail='点击启动服务恢复'
        except Exception as error:
            self.state='error'; self.summary='状态查询失败'; self.detail=str(error)
        if self.icon:
            self.icon.icon=tray_image(self.state)
            self.icon.title=(t('本地知识库',self.config.directory)+': '+t(self.summary,self.config.directory)+'\n'+t(self.detail,self.config.directory))[:120]
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
            item(lambda entry:t(controller.summary,config.directory),None,enabled=False),
            item(lambda entry:t(controller.detail,config.directory),None,enabled=False), pystray.Menu.SEPARATOR,
            item(lambda entry:t('打开网页',config.directory),invoke('open'),default=True), item(lambda entry:t('刷新状态',config.directory),invoke('refresh')),
            pystray.Menu.SEPARATOR,
            *[item(lambda entry,label=label:t(label,config.directory),invoke(action),enabled=lambda entry:not controller.busy.locked())
              for label,action in [('启动服务','start'),('停止服务','stop'),('重启服务','restart')]],
            pystray.Menu.SEPARATOR,
            item(lambda entry:t('查看日志',config.directory),invoke('logs')),
            item(lambda entry:t('取消登录启动' if controller.autostart else '恢复登录启动',config.directory),
                 lambda icon,entry:controller.action('disable-autostart' if controller.autostart else 'enable-autostart')),
            item(lambda entry:t('退出',config.directory),invoke('exit'),enabled=lambda entry:not controller.busy.locked()),
        )
        icon=pystray.Icon('vault-rag',tray_image('stopped'),t('本地知识库',config.directory),menu)
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
