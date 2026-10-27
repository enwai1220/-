"""Permanent launcher. Reuse legacy 3010 without interrupting it; start compatible backend when needed."""
import argparse, ctypes, json, socket, subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:3010/'
COMPAT_URL='http://127.0.0.1:3012/'
client=urllib.request.build_opener(urllib.request.ProxyHandler({}))

def healthy(require_triage=False,url=None):
 try:
  with client.open((url or URL)+'api/health',timeout=2) as response:
   data=json.load(response)
   return data.get('app')=='failure-immunity' and (not require_triage or 'work-life-triage' in data.get('features',[]))
 except Exception:return False

def ensure_service(url,require_triage=False):
 if healthy(require_triage,url):return
 from urllib.parse import urlparse
 port=urlparse(url).port
 with socket.socket() as sock:
  if sock.connect_ex(('127.0.0.1',port))==0:raise RuntimeError(str(port)+' 已被其他服务占用，请联系维护；未关闭任何服务。')
 logs=ROOT/'data'/'logs';logs.mkdir(parents=True,exist_ok=True)
 python=Path(sys.executable).with_name('pythonw.exe')
 if not python.exists():python=Path(sys.executable)
 with (logs/('server-'+str(port)+'.log')).open('ab') as out,(logs/('error-'+str(port)+'.log')).open('ab') as err:
  subprocess.Popen([str(python),str(ROOT/'backend/server.py'),'--port',str(port)],cwd=ROOT,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
 deadline=time.monotonic()+30
 while not healthy(require_triage,url):
  if time.monotonic()>deadline:raise RuntimeError('启动失败，请检查 data/logs/error-'+str(port)+'.log。')
  time.sleep(.4)

def main(open_browser=True):
 ensure_service(URL)
 if not healthy(require_triage=True):ensure_service(COMPAT_URL,require_triage=True)
 if open_browser:webbrowser.open(URL)
 if sys.stdout:print('失败免疫练习已就绪：'+URL)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--no-open',action='store_true');args=parser.parse_args()
 try:main(not args.no_open)
 except Exception as error:
  if args.no_open:raise
  ctypes.windll.user32.MessageBoxW(0,str(error),'失败免疫练习启动失败',16)
