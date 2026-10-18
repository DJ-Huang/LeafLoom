import {Diagnostic} from './i18n';
import {t,useLocale} from './i18n';
import React,{useEffect,useRef,useState} from 'react';
import {media} from './api';
export function VideoPlayer({path,active=true,stateKey='media:'+path,root}:{path:string,active?:boolean,stateKey?:string,root?:string}){
 useLocale();
 const player=useRef<HTMLVideoElement>(null);const [duration,setDuration]=useState(0);const [seconds,setSeconds]=useState('0');const [playing,setPlaying]=useState(false);const [error,setError]=useState('');
 useEffect(()=>{if(!active)player.current?.pause();},[active]);
 useEffect(()=>{const video=player.current;return()=>{if(video){sessionStorage.setItem(stateKey+':seconds',String(video.currentTime));video.pause();}};},[stateKey]);
 return <div className="video-player"><video ref={player} controls preload={active?'metadata':'none'} src={media(path,false,root)} onTimeUpdate={()=>{if(player.current)sessionStorage.setItem(stateKey+':seconds',String(player.current.currentTime));}} onLoadedMetadata={()=>{setDuration(player.current?.duration||0);if(player.current)player.current.currentTime=Math.min(Number(sessionStorage.getItem(stateKey+':seconds')||0),player.current.duration||0);}} onPlay={()=>setPlaying(true)} onPause={()=>setPlaying(false)} onError={()=>setError(t("浏览器无法播放此编码，可以下载原文件打开。"))}/><div className="video-actions"><button disabled={!duration} onClick={async()=>{const video=player.current;if(!video)return;if(!video.paused)video.pause();else try{await video.play();}catch(e){setError(String(e));}}}>{playing?t("暂停"):t("播放")}</button><label>{t("跳转秒数")}{" "}<input aria-label={t("跳转秒数")} type="number" min="0" max={duration||undefined} step="1" value={seconds} onChange={e=>setSeconds(e.target.value)}/></label><button disabled={!duration} onClick={()=>{if(player.current)player.current.currentTime=Math.max(0,Math.min(Number(seconds)||0,duration));}}>{t("跳转")}</button>{duration>0&&<span className="subtle">{t("共")}{" "}{Math.ceil(duration)} {" "}{t("秒")}</span>}</div>{error&&<p className="error">{<Diagnostic message={error}/>}</p>}</div>;
}
export function AudioPlayer({path,active=true,stateKey='media:'+path,root}:{path:string,active?:boolean,stateKey?:string,root?:string}){
 useLocale();
 const player=useRef<HTMLAudioElement>(null);
 useEffect(()=>{if(!active)player.current?.pause();},[active]);
 useEffect(()=>{const audio=player.current;return()=>{if(audio){sessionStorage.setItem(stateKey+':seconds',String(audio.currentTime));audio.pause();}};},[stateKey]);
 return <audio ref={player} controls preload={active?'metadata':'none'} src={media(path,false,root)} onTimeUpdate={()=>{if(player.current)sessionStorage.setItem(stateKey+':seconds',String(player.current.currentTime));}} onLoadedMetadata={()=>{if(player.current)player.current.currentTime=Math.min(Number(sessionStorage.getItem(stateKey+':seconds')||0),player.current.duration||0);}}/>;
}
