from pathlib import Path
import ctypes, datetime, sys, traceback, webbrowser
from launcher import main, URL
if __name__=='__main__':
 log=Path(__file__).resolve().parents[1]/'data/logs/launcher.log'
 log.parent.mkdir(parents=True,exist_ok=True)
 def record(text):
  with log.open('a',encoding='utf-8') as stream:stream.write(datetime.datetime.now().isoformat()+' '+text+'\n')
 record('Open Things requested')
 try:
  if sys.stdout:print('正在检查并更新本机服务，请稍候…',flush=True)
  main(open_browser=False)
  record('Things backend ready')
  webbrowser.open(URL+'?page=things')
 except Exception as error:
  record(traceback.format_exc())
  if sys.stdout:print(str(error),flush=True)
  else:ctypes.windll.user32.MessageBoxW(0,str(error),'事情梳理启动失败',16)
  raise SystemExit(1)
