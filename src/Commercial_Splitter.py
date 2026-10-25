"""Commercial Splitter 4.9.1 — Recovery checkpoints and interrupted-session detection."""
import math, hashlib, json, os, subprocess, sys, re, csv, tempfile, time, traceback, threading, shutil, bisect, urllib.request, urllib.error
from pathlib import Path
from PySide6.QtCore import QSize, Qt, QThread, Signal, QTimer, QProcess, QUrl, QEvent, QMimeData, QPoint
from PySide6.QtGui import QAction, QPixmap, QIcon, QShortcut, QKeySequence, QDesktopServices, QPainter, QColor, QPen, QBrush, QCursor, QDrag, QMouseEvent
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QTextEdit,QPlainTextEdit,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QStackedWidget,QFileDialog,QFrame,QScrollArea,QGridLayout,QLineEdit,QCheckBox,QMessageBox,QProgressBar,QComboBox,QSpinBox,QGroupBox,QListWidget,QListWidgetItem,QDoubleSpinBox,QFormLayout,QSlider,QDialog,QDialogButtonBox,QTabWidget,QKeySequenceEdit,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QSplitter,QMenu,QSizePolicy,QInputDialog)

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
EXE_DIR=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else ROOT
VIDEO_FILTER='Videos (*.mp4 *.mkv *.webm *.mov *.avi *.ts *.m4v *.mpg *.mpeg);;All files (*)'
APPDATA=Path(os.environ.get('LOCALAPPDATA') or (Path.home()/'.local'/'share'))/'CommercialSplitter'
PREFS_FILE=APPDATA/'preferences.json'
def safe_folder_name(value):
 value=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip().rstrip('. ')
 if value.upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:value+='_'
 return value[:120].rstrip('. ') or 'Recording'

def log_load(message):
 try:
  APPDATA.mkdir(parents=True,exist_ok=True)
  with (APPDATA/'qt_load_diagnostics.log').open('a',encoding='utf-8') as f:
   f.write(time.strftime('%Y-%m-%d %H:%M:%S')+' '+str(message)+'\n')
 except OSError:pass


def tool(name):
 from shutil import which
 exe=name+('.exe' if os.name=='nt' else '')
 bases=[EXE_DIR,ROOT] if getattr(sys,'frozen',False) else [ROOT]
 for base in bases:
  for p in (base/'tools'/exe,base/exe):
   if p.is_file():return str(p)
 return which(exe) or which(name)

def run(cmd,**kw):
 if os.name=='nt':kw['creationflags']=subprocess.CREATE_NO_WINDOW
 return subprocess.run(cmd,**kw)

def fmt(s):
 ms=max(0,round(s*1000));m,r=divmod(ms,60000);sec,milli=divmod(r,1000)
 return f'{m:02}:{sec:02}:{milli:03}'

class OrganizerCard(QPushButton):
 """Drag an original clip ID; never modify source cut timestamps."""
 def __init__(self,owner,clip_id):
  super().__init__();self.owner=owner;self.clip_id=clip_id;self.press_pos=None
  self.setAcceptDrops(True)
 def mousePressEvent(self,event):
  if event.button()==Qt.LeftButton:self.press_pos=event.position().toPoint()
  super().mousePressEvent(event)
 def mouseMoveEvent(self,event):
  if self.press_pos is not None and event.buttons() & Qt.LeftButton:
   if (event.position().toPoint()-self.press_pos).manhattanLength()>=QApplication.startDragDistance():
    self.press_pos=None
    drag=QDrag(self);mime=QMimeData();mime.setData('application/x-commercialsplitter-clip',str(self.clip_id).encode())
    drag.setMimeData(mime);drag.exec(Qt.MoveAction)
    return
  super().mouseMoveEvent(event)
 def contextMenuEvent(self,event):
  self.owner.organizer_card_menu(self.clip_id,event.globalPos())
 def dragEnterEvent(self,event):
  if event.mimeData().hasFormat('application/x-commercialsplitter-clip'):event.acceptProposedAction()
 def dragMoveEvent(self,event):
  if event.mimeData().hasFormat('application/x-commercialsplitter-clip'):event.acceptProposedAction()
 def dropEvent(self,event):
  try:source=int(bytes(event.mimeData().data('application/x-commercialsplitter-clip')).decode())
  except (ValueError,UnicodeDecodeError):return
  after=event.position().x()>=self.width()/2
  self.owner.reorder_clip(source,self.clip_id,after=after)
  event.acceptProposedAction()

class ReleaseCheckWorker(QThread):
 """Fetch public GitHub release metadata only."""
 result=Signal(object)
 def __init__(self,channel='stable',parent=None):
  super().__init__(parent);self.channel=channel
 def run(self):
  try:
   endpoint='releases/latest' if self.channel=='stable' else 'releases?per_page=30'
   req=urllib.request.Request('https://api.github.com/repos/Longthony/Commercial-Splitter/'+endpoint,headers={'Accept':'application/vnd.github+json','User-Agent':'CommercialSplitter/4.9.1'})
   with urllib.request.urlopen(req,timeout=12) as response:
    if response.status!=200:raise RuntimeError('GitHub returned HTTP '+str(response.status))
    data=json.load(response)
   candidates=[]
   for release in (data if isinstance(data,list) else [data]):
    if not isinstance(release,dict) or release.get('draft') or (self.channel=='stable' and release.get('prerelease')):continue
    tag=str(release.get('tag_name','')).lstrip('vV')
    if not re.fullmatch(r'\d+\.\d+\.\d+',tag):continue
    url=str(release.get('html_url',''))
    if not url.startswith('https://github.com/Longthony/Commercial-Splitter/releases/'):continue
    candidates.append((tuple(map(int,tag.split('.'))),tag,url,str(release.get('body') or ''),bool(release.get('prerelease'))))
   if not candidates:raise ValueError('No '+self.channel+' releases found on GitHub.')
   _,tag,url,notes,prerelease=max(candidates,key=lambda item:item[0])
   self.result.emit({'version':tag,'url':url,'notes':notes[:2000],'prerelease':prerelease,'channel':self.channel})
  except urllib.error.HTTPError as exc:
   self.result.emit({'error':'No '+self.channel+' release found yet.' if exc.code==404 else 'GitHub returned HTTP '+str(exc.code)})
  except Exception as exc:self.result.emit({'error':str(exc)})

class Worker(QThread):
 ready=Signal(str,object)
 def __init__(self,kind,video,start=0,end=0):
  super().__init__();self.kind=kind;self.video=video;self.start_value=start;self.end=end
  self.cancel_event=threading.Event();self.pause_after_clip=threading.Event();self.process_lock=threading.Lock();self.process=None
 def request_cancel(self):
  self.cancel_event.set()
  with self.process_lock:
   proc=self.process
  if proc and proc.poll() is None:
   try:proc.terminate()
   except OSError:pass
 def run_export_command(self,cmd):
  options={"stdout":subprocess.DEVNULL,"stderr":subprocess.PIPE,"text":True}
  if os.name=='nt':options['creationflags']=subprocess.CREATE_NO_WINDOW
  with self.process_lock:
   if self.cancel_event.is_set():return None
   proc=subprocess.Popen(cmd,**options);self.process=proc
  try:
   try:_,stderr=proc.communicate(timeout=7200)
   except subprocess.TimeoutExpired:
    proc.kill();_,stderr=proc.communicate();raise RuntimeError('FFmpeg export timed out')
   if self.cancel_event.is_set():return None
   if proc.returncode:raise RuntimeError((stderr or 'FFmpeg export failed')[-1000:])
   return True
  finally:
   with self.process_lock:
    if self.process is proc:self.process=None
 def verify_export(self,path,expected_duration,mode):
  probe=tool('ffprobe')
  if not probe:return ('NOT CHECKED','ffprobe not found',None)
  try:
   r=run([probe,'-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)],capture_output=True,text=True,timeout=45)
   if r.returncode: return ('FAIL','ffprobe could not read exported file',None)
   actual=float(r.stdout.strip())
   if not (actual>0):return ('FAIL','Invalid duration',actual)
   difference=abs(actual-expected_duration)
   # MP4 container timing and audio priming can differ slightly from video frames.
   tolerance=max(.15,min(.5,expected_duration*.01)) if mode=='Accurate' else max(.5,min(2.,expected_duration*.03))
   if difference>tolerance:
    return ('WARNING',f'Duration differs by {difference:.3f}s (tolerance {tolerance:.3f}s)',actual)
   if mode!='Accurate':
    return ('WARNING','Fast copy may start at a keyframe instead of the selected cut',actual)
   return ('PASS','Duration within tolerance; boundaries not frame-verified',actual)
  except Exception as e:return ('NOT CHECKED',str(e)[:180],None)
 def boundary_frame_comparison(self,source,export,start,end,actual,mode="Accurate"):
  """Compare actual decoded first/last export frames to nearby source frames.

  A visual heuristic: transcoding, frame timing, and VFR can affect the scores.
  """
  ffmpeg=tool('ffmpeg');probe=tool('ffprobe')
  if not ffmpeg or not probe:return ('NOT CHECKED','FFmpeg or FFprobe missing','','')
  try:
   info=run([probe,'-v','error','-select_streams','v:0','-show_entries','stream=avg_frame_rate','-of','default=noprint_wrappers=1:nokey=1',str(source)],capture_output=True,text=True,timeout=30)
   rate=info.stdout.strip().splitlines()[0].split('/')
   fps=float(rate[0])/float(rate[1]) if len(rate)==2 else float(rate[0])
   if not 1<=fps<=240:return ('NOT CHECKED','Unknown source video frame rate','','')
   frame=1/fps
   # Stream-copy boundaries may be shifted to keyframes; a visual match is not
   # sufficient evidence that the requested timestamp was honored.
   if mode!='Accurate':
    return ('NOT FRAME-EXACT','Fast copy is keyframe-dependent; use Accurate mode to validate intended boundaries','','')
   if end-start<frame*3 or actual<frame*3:return ('NOT CHECKED','Clip too short for boundary verification','','')
   frame_size=64*36*3
   def decode(video,seek=None,limit=None):
    cmd=[ffmpeg,'-hide_banner','-loglevel','error','-nostdin']
    if seek is not None:cmd+=['-ss',f'{max(0.,seek):.6f}']
    cmd+=['-i',str(video),'-map','0:v:0','-an','-sn']
    if limit is not None:cmd+=['-frames:v',str(limit)]
    cmd+=['-vf','scale=64:36,format=rgb24','-c:v','rawvideo','-threads:v','1','-f','rawvideo','-pix_fmt','rgb24','-']
    r=run(cmd,capture_output=True,timeout=75)
    if r.returncode or len(r.stdout)<frame_size:
     err=r.stderr.decode('utf-8','replace').strip() if r.stderr else ''
     raise RuntimeError(f'Frame decode failed (exit {r.returncode}, bytes {len(r.stdout)}): {err[-180:]}')
    return [r.stdout[i:i+frame_size] for i in range(0,len(r.stdout)-frame_size+1,frame_size)]
   # Read the first decoded export frame, not a seeked approximation.
   exported_first=decode(export,limit=1)[0]
   # Read the actual last decoded export frame by decoding a bounded tail.
   # Retry from earlier if the tail seek lands after the last video frame.
   exported_last=None
   for back in (1.5,4.,10.):
    try:
     frames=decode(export,seek=max(0.,actual-back))
     exported_last=frames[-1]
     break
    except RuntimeError:continue
   if exported_last is None:return ('NOT CHECKED','Could not decode final exported video frame','','')
   # Compare each exported boundary frame to a small set of candidate
   # source frames. This tolerates sub-frame seek differences and reports
   # visual similarity without claiming exact frame identity.
   source_first=decode(source,seek=max(0.,start-frame),limit=4)
   source_last=decode(source,seek=max(0.,end-4*frame),limit=6)
   def error(a,b):return sum(abs(x-y) for x,y in zip(a,b))/frame_size
   first_error=min(error(exported_first,f) for f in source_first)
   last_error=min(error(exported_last,f) for f in source_last)
   worst=max(first_error,last_error)
   status='REVIEW' if worst>24 else 'SIMILAR (HEURISTIC)'
   note=('First/last decoded export frames compared against nearby source frames. '
         'Similarity is a visual heuristic, NOT proof of frame-exact cutting; VFR sources may differ.')
   if status=='REVIEW':note='Potential boundary mismatch. '+note
   return (status,note,f'{first_error:.2f}',f'{last_error:.2f}')
  except Exception as exc:return ('NOT CHECKED',str(exc)[:450],'','')
 def run(self):
  try:
   if self.kind=='probe':
    result=run([tool('ffprobe') or 'ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',self.video],capture_output=True,text=True,timeout=35,check=True)
    self.ready.emit('probe',float(result.stdout.strip()))
   elif self.kind=='scan':
    threshold=self.start_value;gap=self.end
    cmd=[tool('ffmpeg') or 'ffmpeg','-hide_banner','-nostdin','-i',self.video,'-vf',f"select='gt(scene,{threshold})',showinfo",'-an','-f','null','-']
    result=run(cmd,capture_output=True,text=True,timeout=7200)
    if result.returncode:raise RuntimeError(result.stderr[-1500:])
    times=[]
    for line in result.stderr.splitlines():
     if 'showinfo' not in line:continue
     m=re.search(r'pts_time:\s*([0-9.]+)',line)
     if m:
      t=float(m.group(1))
      if t>0 and (not times or t-times[-1]>=gap):times.append(t)
    self.ready.emit('scan',times)
   elif self.kind=='export':
    output,rows,mode,preset=self.extra
    done=[];checks=[]
    for i,(index,a,b,name) in enumerate(rows,1):
     if not self.cancel_event.is_set():self.ready.emit('export_clip_started',(i,len(rows),index,name))
     # Wait at clip boundaries only; never interrupt an active FFmpeg export.
     if self.pause_after_clip.is_set() and not self.cancel_event.is_set():
      self.ready.emit('export_paused',(i-1,len(rows)))
     while self.pause_after_clip.is_set() and not self.cancel_event.is_set():
      self.cancel_event.wait(0.1)
     if self.cancel_event.is_set():break
     target=Path(output)/name
     tmp=target.with_name(target.stem+'.commercialsplitter-partial.mp4')
     cmd=[tool('ffmpeg') or 'ffmpeg','-hide_banner','-loglevel','error','-y','-nostdin']
     # Preserve the tested v4.4.4 Accurate seek behavior.
     if mode=='Accurate':cmd+=['-i',self.video,'-ss',f'{a:.6f}','-t',f'{b-a:.6f}']
     else:cmd+=['-ss',f'{a:.3f}','-i',self.video,'-t',f'{b-a:.3f}']
     preset_opts={'Balanced':('medium','20'),'High Quality':('slow','17'),'Smaller File':('slow','25'),'Fast Encode':('veryfast','21')}
     speed,crf=preset_opts.get(preset,('medium','20'))
     cmd+=(['-c:v','libx264','-preset',speed,'-crf',crf,'-c:a','aac','-b:a','192k','-movflags','+faststart'] if mode=='Accurate' else ['-c','copy'])
     cmd.append(str(tmp))
     try:
      success=self.run_export_command(cmd)
      if not success or self.cancel_event.is_set():break
      if not tmp.is_file() or tmp.stat().st_size==0:
       raise RuntimeError(f'Clip {index} ({name}): FFmpeg produced no usable output file')
      os.replace(tmp,target)
      if not target.is_file() or target.stat().st_size==0:
       raise RuntimeError(f'Clip {index} ({name}): output file is missing or empty')
      status,detail,actual=self.verify_export(target,b-a,mode)
      frame_status,frame_detail,first_error,last_error=self.boundary_frame_comparison(self.video,target,a,b,actual,mode) if actual is not None else ('NOT CHECKED','Duration probe failed','','')
      checks.append((index,name,f'{b-a:.6f}',f'{actual:.6f}' if actual is not None else '',status,detail,frame_status,first_error,last_error,frame_detail))
     except Exception as exc:
      self.ready.emit('export_clip_failed',(i,len(rows),index,name,str(exc),len(done),list(checks)))
      return
     finally:
      if tmp.exists():tmp.unlink()
     done.append((index,a,b,name));self.ready.emit('export_progress',(i,len(rows),name))
    # On cancellation preserve completed clips; do not replace a prior manifest
    # with a misleading incomplete export manifest.
    if self.cancel_event.is_set():
     self.ready.emit('export_cancelled',(len(done),len(rows)))
    else:
     manifest=Path(output)/'boundaries.csv'
     manifest_tmp=Path(output)/'boundaries.commercialsplitter-partial.csv'
     try:
      with manifest_tmp.open('w',newline='',encoding='utf-8') as f:
       writer=csv.writer(f);writer.writerow(['clip','filename','start_seconds','end_seconds','duration_seconds'])
       for index,a,b,name in done:writer.writerow([index,name,f'{a:.3f}',f'{b:.3f}',f'{b-a:.3f}'])
      os.replace(manifest_tmp,manifest)
     finally:
      if manifest_tmp.exists():manifest_tmp.unlink()
     verification=Path(output)/'export_verification.csv'
     verification_tmp=Path(output)/'export_verification.commercialsplitter-partial.csv'
     try:
      with verification_tmp.open('w',newline='',encoding='utf-8') as f:
       writer=csv.writer(f)
       writer.writerow(['clip','filename','expected_duration_seconds','actual_duration_seconds','status','details','boundary_status','first_decoded_frame_min_pixel_error','last_decoded_frame_min_pixel_error','boundary_details'])
       writer.writerows(checks)
      os.replace(verification_tmp,verification)
     finally:
      if verification_tmp.exists():verification_tmp.unlink()
     self.ready.emit('export_done',(len(done),checks))
   elif self.kind=='thumbnail':
    result=run([tool('ffmpeg') or 'ffmpeg','-hide_banner','-loglevel','error','-ss',f'{self.start_value:.3f}','-i',self.video,'-frames:v','1','-vf','scale=400:225:force_original_aspect_ratio=decrease,pad=400:225:(ow-iw)/2:(oh-ih)/2','-f','image2pipe','-vcodec','png','-'],capture_output=True,timeout=30,check=True)
    self.ready.emit('thumbnail',result.stdout)
  except Exception as e:self.ready.emit('error',str(e))

def propose_boundaries(times, duration, silences=()):
 """Conservative duration-aware candidate selection; scores are heuristic, not probabilities."""
 points=sorted(set(round(float(t),3) for t in times if 2<float(t)<duration-2))
 if not points:return []
 # DP chooses a plausible chain without treating every internal shot change as an ad break.
 nodes=[0.0]+points+[duration];n=len(nodes)
 best=[-1e9]*n;prev=[None]*n;best[0]=0
 def segment_score(length):
  if length<4:return -12
  if 5<=length<=11:return 1.5  # bumper
  if 13<=length<=65:return 2.4
  if length<=75:return 0.5
  return -min(12,(length-75)/10)
 for j in range(1,n):
  for i in range(max(0,j-250),j):
   span=nodes[j]-nodes[i]
   if span>150 and i>0:continue
   # Small per-boundary penalty prevents splitting on every shot change.
   evidence=0 if j==n-1 else (2.5 if any(abs(nodes[j]-x)<0.55 for x in silences) else 0)
   score=best[i]+segment_score(span)+(evidence if j<n-1 else 0)-(1.5 if j<n-1 else 0)
   if score>best[j]:best[j]=score;prev[j]=i
 selected=set();k=n-1
 while k and prev[k] is not None:
  if k<n-1:selected.add(k)
  k=prev[k]
 results=[]
 for j in sorted(selected):
  t=nodes[j];gap=min((abs(t-x) for x in silences),default=1e9)
  level='Silence nearby' if gap<.55 else 'Unverified'
  results.append((t,level,'Audio silence nearby' if gap<.55 else 'Duration/scene pattern'))
 return results

class DropZone(QFrame):
 dropped=Signal(str)
 def __init__(self):
  super().__init__();self.setAcceptDrops(True);self.setObjectName('dropzone')
  layout=QVBoxLayout(self);layout.setAlignment(Qt.AlignCenter);layout.setSpacing(10)
  self.title=QLabel('Drag and drop your recording');self.title.setObjectName('dropTitle');self.title.setAlignment(Qt.AlignCenter)
  self.subtitle=QLabel('MP4  •  MKV  •  WEBM  •  MOV  •  AVI  •  TS');self.subtitle.setObjectName('dropSubtitle');self.subtitle.setAlignment(Qt.AlignCenter)
  self.pick=QPushButton('Browse Video Files…');self.pick.setObjectName('primary');self.pick.setMinimumWidth(205)
  layout.addStretch();layout.addWidget(self.title);layout.addWidget(self.subtitle);layout.addSpacing(8);layout.addWidget(self.pick,alignment=Qt.AlignCenter);layout.addStretch()
 def dragEnterEvent(self,event):
  if event.mimeData().hasUrls():event.acceptProposedAction()
 def dropEvent(self,event):
  urls=event.mimeData().urls()
  if urls and urls[0].isLocalFile():self.dropped.emit(urls[0].toLocalFile());event.acceptProposedAction()

class CutTimeline(QWidget):
 """Interactive timeline; all edits are committed through Main for recovery/export synchronization."""
 def __init__(self,owner):
  super().__init__(owner);self.owner=owner;self.selected=None;self.dragging=False;self.scrubbing=False;self.scrub_time=None;self.drag_time=None;self.last_preview_seek=0.0;self.hovered_marker=None;self.setFixedHeight(330);self.setMouseTracking(True);self.setFocusPolicy(Qt.StrongFocus)
  # Scroll the zoomed time range when a dragged marker reaches either edge.
  self.drag_scroll_timer=QTimer(self);self.drag_scroll_timer.setInterval(35)
  self.drag_scroll_timer.timeout.connect(self.drag_scroll_tick)
  self.drag_pointer_x=None
 def geometry_data(self):
  return 20,max(1,self.width()-40),max(.001,self.owner.duration)
 def x_for(self,t):
  left,width,duration=self.geometry_data();start,end=self.owner.timeline_visible_range()
  return left+width*(t-start)/max(.001,end-start)
 def time_for(self,x):
  left,width,duration=self.geometry_data();start,end=self.owner.timeline_visible_range()
  return self.owner.timeline_snap_time(max(.001,min(duration-.001,start+(x-left)*(end-start)/width)))
 def paintEvent(self,event):
  p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
  p.fillRect(self.rect(),QColor('#141c28'))
  left,width,duration=self.geometry_data();start,end=self.owner.timeline_visible_range();mode=self.owner.timeline_wave_mode.currentIndex();y=249 if mode==1 else 105;h=65
  # Draw ruler ticks at actual visible timestamps, with labels spaced to
  # avoid overlap at small window widths and high zoom levels.
  p.setPen(QColor('#aebbd0'))
  label_width=88
  divisions=max(2,min(10,int(width//label_width)))
  for i in range(divisions+1):
   t=start+(end-start)*i/divisions
   x=left+width*i/divisions
   text=fmt(t)
   text_x=max(left,min(left+width-label_width,x-label_width/2))
   p.drawText(int(text_x),15,label_width,18,Qt.AlignCenter,text)
   p.setPen(QColor('#354257'))
   p.drawLine(int(x),34,int(x),y+h+10)
   p.setPen(QColor('#aebbd0'))
  # Filmstrip thumbnails are drawn below the time ruler, independent of split edits.
  tiles=self.owner.timeline_thumbs
  if tiles:
   count=len(tiles);tile_w=width/count
   for i,pix in enumerate(tiles):
    x=int(left+i*tile_w);w=max(1,int(left+(i+1)*tile_w)-x)
    if pix and not pix.isNull():
     scaled=pix.scaled(w,62,Qt.KeepAspectRatio,Qt.SmoothTransformation)
     p.fillRect(x,37,w,62,QColor('#111923'))
     p.save();p.setClipRect(x,37,w,62);p.drawPixmap(x+(w-scaled.width())//2,37+(62-scaled.height())//2,scaled);p.restore()
    else:p.fillRect(x,37,w,62,QColor('#293747'))
    p.setPen(QColor('#556172'));p.drawLine(x,37,x,99)
  # Waveform display modes: inside clips, above clips, or hidden.
  peaks=self.owner.timeline_waveform
  # Normalize once per repaint; draw the waveform once instead of once per clip.
  ordered=sorted(peaks) if peaks and mode!=2 else []
  reference=max(.008,ordered[min(len(ordered)-1,int(len(ordered)*.96))]) if ordered else 1.
  if mode==1:
   p.fillRect(int(left),102,int(width),142,QColor('#1c2937'))
   if peaks:
    p.setPen(QPen(QColor('#52dccc'),1))
    for i,amp in enumerate(peaks):
     x=int(left+(i+.5)*width/len(peaks))
     strength=min(1.,(max(0.,amp)/reference)**.58)
     hh=max(1,int(strength*66))
     p.drawLine(x,173-hh,x,173+hh)
   else:
    p.setPen(QColor('#7f91a2'));p.drawText(int(left+8),173,'Audio waveform loading…' if self.owner.timeline_wave_process else 'Audio waveform unavailable')
  displayed_cuts=list(self.owner.cuts)
  if self.dragging and self.selected is not None and self.drag_time is not None and self.selected<len(displayed_cuts):
   displayed_cuts[self.selected]=self.drag_time
  sorted_cuts=sorted(displayed_cuts)
  bounds=[start]+[t for t in sorted_cuts if start<t<end]+[end]
  colors=['#35637a','#3c776d','#75618e','#846748']
  for a,b in zip(bounds,bounds[1:]):
   clip_index=bisect.bisect_right(sorted_cuts,(a+b)/2)
   x1=self.x_for(a);x2=self.x_for(b)
   p.fillRect(int(x1),y,max(1,int(x2-x1)),h,QColor(colors[clip_index%len(colors)]))
  if peaks and mode==0:
   # Clip colors already cover the entire visible track, so there is no
   # need to redraw the same 1000 waveform samples for each split segment.
   p.save();p.setClipRect(int(left),y,int(width),h)
   p.setPen(QPen(QColor(220,255,245,175),1))
   for j,amp in enumerate(peaks):
    px=int(left+(j+.5)*width/len(peaks))
    strength=min(1.,(max(0.,amp)/reference)**.58)
    hh=max(1,int(strength*25))
    p.drawLine(px,y+h//2-hh,px,y+h//2+hh)
   p.restore()
  for a,b in zip(bounds,bounds[1:]):
   x1=self.x_for(a);x2=self.x_for(b)
   if x2-x1>35:
    p.setPen(QColor('white'))
    p.drawText(int(x1+5),y+16,f'Clip {bisect.bisect_right(sorted_cuts,(a+b)/2)+1}')
  for i,t in enumerate(displayed_cuts):
   if not start<=t<=end:continue
   x=int(self.x_for(t));active=i==self.selected or i==self.hovered_marker
   # Color reflects the accepted candidate linked to this boundary.
   # Unknown boundaries retain amber rather than claiming a confidence level.
   marker_color='#f5b84b'
   for candidate in self.owner.candidates:
    if not candidate.get('keep') or candidate.get('rejected'):continue
    if abs(float(candidate.get('time',-9999))-t)>.035:continue
    conf=str(candidate.get('confidence','')).lower()
    source=str(candidate.get('source','')).lower()
    marker_color=('#68b4f6' if conf=='manual' or source.startswith('timeline manual')
                  else '#b89afa' if conf=='low' else '#50b992')
    break
   p.setPen(QPen(QColor(marker_color),5 if active else 3));p.drawLine(x,y-12,x,y+h+7)
   if active:
    p.setBrush(QColor(marker_color));p.drawEllipse(x-6,y-19,12,12)
    p.setPen(QColor('#f5f9ff'));p.drawText(max(4,min(self.width()-104,x-52)),y-43,104,18,Qt.AlignCenter,fmt(t))
   if self.dragging and i==self.selected:
    p.setPen(QColor('#ffffff'));p.drawText(max(20,min(self.width()-110,x-55)),y-23,110,18,Qt.AlignCenter,fmt(t))

  playhead_time=self.scrub_time if self.scrubbing and self.scrub_time is not None else self.owner.timeline_player.position()/1000
  x=int(self.x_for(playhead_time));p.setPen(QPen(QColor('#ff6e79'),2));p.drawLine(x,29,x,y+h+15)
  p.end()
 def wheelEvent(self,event):
  if not 29<=event.position().y()<=self.height() or not self.owner.timeline_wheel_zoom(event.angleDelta().y(),event.globalPosition().toPoint()):
   event.ignore()
  else:
   event.accept()
 def drag_scroll_tick(self):
  if not self.dragging or self.selected is None or self.owner.timeline_zoom_factor<=1 or not self.owner.duration:
   self.drag_scroll_timer.stop();return
  left,width,_=self.geometry_data();right=left+width
  x=self.mapFromGlobal(QCursor.pos()).x()
  edge=52
  direction=-1 if x<left+edge else (1 if x>right-edge else 0)
  if not direction:
   self.drag_scroll_timer.stop();return
  strength=min(1.,max(.12,(left+edge-x)/edge if direction<0 else (x-(right-edge))/edge))
  start,end=self.owner.timeline_visible_range();span=end-start
  new_start=max(0.,min(self.owner.duration-span,start+direction*span*(.006+.028*strength)))
  if abs(new_start-start)<1e-8:return
  self.owner.timeline_pan.setValue(round(1000*new_start/max(.001,self.owner.duration-span)))
  # The dragged cut follows the cursor as the visible time range moves.
  self.update_drag_time(x)
 def update_drag_time(self,x):
  if self.selected is None or self.selected>=len(self.owner.cuts):return
  left,width,_=self.geometry_data()
  t=self.time_for(max(left,min(left+width,x)))
  t=self.owner.timeline_snap_time(self.owner.timeline_smart_snap_time(t,exclude=self.owner.cuts[self.selected]))
  self.drag_time=t
  self.owner.timeline_time_label.setText('Move split to '+fmt(t))
  self.update()
  now=time.monotonic()
  if now-self.last_preview_seek>=0.07:
   self.owner.timeline_player.setPosition(round(t*1000));self.last_preview_seek=now
 def mousePressEvent(self,event):
  if not self.owner.video:return
  self.setFocus(Qt.MouseFocusReason)  # Keyboard Delete targets the selected timeline marker.
  x=event.position().x();hits=[(abs(self.x_for(t)-x),i) for i,t in enumerate(self.owner.cuts)]
  clip_y=249 if self.owner.timeline_wave_mode.currentIndex()==1 else 105
  if hits and event.position().y()>=clip_y-12 and min(hits)[0]<=11 and self.owner.timeline_visible_range()[0]<=self.owner.cuts[min(hits)[1]]<=self.owner.timeline_visible_range()[1]:
   self.selected=min(hits)[1];self.dragging=False;self.marker_pressed=True;self.marker_press_x=x;self.drag_time=self.owner.cuts[self.selected]
   self.last_preview_seek=0.0
   self.owner.timeline_player.pause()
   self.owner.timeline_player.setPosition(round(self.owner.cuts[self.selected]*1000))
   self.owner.timeline_request_split_preview(cut_time=self.owner.cuts[self.selected])
  else:
   self.selected=None;self.marker_pressed=False;self.scrubbing=True;self.scrub_time=self.time_for(x);self.last_preview_seek=0.0
   self.owner.timeline_player.pause();self.owner.timeline_player.setPosition(round(self.scrub_time*1000))
   self.owner.timeline_request_split_preview(cut_time=self.scrub_time,live=True)
  self.update();self.owner.timeline_selection_changed()
 def mouseMoveEvent(self,event):
  if not self.dragging and not self.scrubbing and not getattr(self,'marker_pressed',False):
   x=event.position().x();y=event.position().y()
   clip_y=249 if self.owner.timeline_wave_mode.currentIndex()==1 else 105
   hits=[(abs(self.x_for(t)-x),i) for i,t in enumerate(self.owner.cuts) if self.owner.timeline_visible_range()[0]<=t<=self.owner.timeline_visible_range()[1]]
   hovered=min(hits)[1] if hits and y>=clip_y-22 and y<=clip_y+78 and min(hits)[0]<=11 else None
   if hovered!=self.hovered_marker:self.hovered_marker=hovered;self.update()
   self.setCursor(Qt.SizeHorCursor if hovered is not None else Qt.ArrowCursor)
  if getattr(self,"marker_pressed",False) and self.selected is not None:
   if abs(event.position().x()-self.marker_press_x)>=QApplication.startDragDistance()+3:
    self.marker_pressed=False;self.dragging=True
  if self.scrubbing:
   t=self.time_for(event.position().x());self.scrub_time=t
   self.owner.timeline_time_label.setText(fmt(t)+" / "+fmt(self.owner.duration))
   self.update()
   now=time.monotonic()
   if now-self.last_preview_seek>=0.07:
    self.owner.timeline_player.setPosition(round(t*1000));self.last_preview_seek=now
    self.owner.timeline_request_split_preview(cut_time=t,live=True)
  if self.dragging and self.selected is not None:
   self.update_drag_time(event.position().x())
   if self.owner.timeline_zoom_factor>1:self.drag_scroll_timer.start()
   else:self.drag_scroll_timer.stop()
 def mouseReleaseEvent(self,event):
  self.drag_scroll_timer.stop()
  if getattr(self,"marker_pressed",False):
   self.marker_pressed=False;self.drag_time=None
   self.update();return
  if self.scrubbing:
   t=self.time_for(event.position().x());self.scrubbing=False;self.scrub_time=None
   self.owner.timeline_player.setPosition(round(t*1000))
   self.owner.timeline_request_split_preview(cut_time=t,live=True)
  if self.dragging and self.selected is not None:
   index=self.selected
   t=self.drag_time if self.drag_time is not None else self.time_for(event.position().x())
   self.dragging=False;self.drag_time=None
   self.owner.timeline_player.setPosition(round(t*1000))
   self.owner.timeline_move_cut(index,t)
   self.owner.timeline_selection_changed()
  self.update()
 def leaveEvent(self,event):
  self.hovered_marker=None;self.setCursor(Qt.ArrowCursor);self.update()
  super().leaveEvent(event)

class Main(QMainWindow):
 def __init__(self):
  super().__init__();self.setWindowTitle('Commercial Splitter 4.9.0');self.resize(1120,780);self.setMinimumSize(650,450)
  self.video=None;self.duration=0;self.fps=30.0;self.cuts=[];self.candidates=[];self.clip_names={};self.clip_order=[];self.workers=[];self.thumbnails={};self.preview_generation=0;self.busy=False;self.probe_process=None;self.probe_timer=None;self.probe_id=0;self.preview_generation=0;self.preview_workers=[];self.scan_process=None;self.scan_times=[];self.scan_buffer="";self.scan_timer=None;self.frame_processes={};self.scan_elapsed=0.0;self.scan_token=0;self.playback_processes=[];self.export_worker=None;self.auto_process=None;self.auto_timer=None;self.auto_token=0;self.auto_buffer="";self.auto_silences=[];self.auto_black_intervals=[];self.auto_black_start=None;self.auto_visual_times=[];self.auto_silence_intervals=[];self.auto_silence_start=None;self.last_export_folder=None;self.export_queue=[];self.export_queue_paused=False;self.queue_stop_requested=False;self.active_queue_job=None;self.queue_completed=0;self.queue_failed=0;self.export_started_at=None;self.project_path=None;self.pending_project=None;self.prefs=self.load_preferences();self.saved_project_signature=None;self.project_dirty=False;self.autosave_elapsed=0;self.recovery_checkpoint_at={};self.recent_projects=list(self.prefs.get('recent_projects',[]));self.dashboard_thumb_queue=[];self.dashboard_thumb_proc=None;self.default_export_root=self.prefs['default_export_folder'];self.export_queue=self.restore_export_queue()
  base=QWidget();self.setCentralWidget(base);outer=QVBoxLayout(base);outer.setContentsMargins(20,14,20,14);outer.setSpacing(11)
  head=QHBoxLayout();brand=QLabel('◧  Commercial Splitter');brand.setObjectName('brand');head.addWidget(brand);head.addStretch()
  settings=QPushButton('⚙  Settings');settings.setObjectName('quiet');settings.clicked.connect(self.show_settings);head.addWidget(settings);outer.addLayout(head)
  nav=QHBoxLayout();nav.setSpacing(7);self.nav=[]
  for index,label in ((4,'Projects'),(0,'Import && Scan'),(2,'Timeline && Review'),(3,'Export')):
   b=QPushButton(label);b.setObjectName('sectionNav');b.setCheckable(True);b.setMinimumHeight(40);b.setMinimumWidth(100);b.setToolTip({4:'Browse projects in your default project folder',0:'Import a video and scan for commercial boundaries',2:'Edit the Timeline and review detected cuts',3:'Organize clips and export commercials'}[index]);b.clicked.connect(lambda _,i=index:self.go(i));self.nav.append((index,b));nav.addWidget(b)
  nav.addStretch();outer.addLayout(nav)
  self.stack=QStackedWidget();outer.addWidget(self.stack,1)
  self.make_import();self.make_review();self.make_timeline();self.make_export();self.make_dashboard();self.combine_timeline_review()
  # Keep the status label for internal messages without reserving a bottom footer.
  self.status=QLabel('Ready — choose a recording to begin',self)
  self.status.hide()
  self.autosave_timer=QTimer(self);self.autosave_timer.setInterval(10000);self.autosave_timer.timeout.connect(self.autosave_tick);self.autosave_timer.start()
  self.build_menu();self.setup_shortcuts();self.export_mode.setCurrentText(self.prefs['default_export_mode']);self.apply_theme();self.show_dashboard()
  # Restore the previous main-window dimensions, position, and maximized state.
  # Qt checks available screens and rejects invalid window geometry.
  saved_geometry=self.prefs.get('main_window_geometry','')
  if isinstance(saved_geometry,str) and saved_geometry:
   try:
    import base64
    self.restoreGeometry(base64.b64decode(saved_geometry,validate=True))
   except (ValueError,TypeError,Exception):
    pass
  self.session_marker=APPDATA/'session_active.json'
  self.previous_interrupted_session=self.read_interrupted_session()
  self.write_session_marker()
  if self.previous_interrupted_session:QTimer.singleShot(450,self.offer_interrupted_session_recovery)
  if self.prefs.get('startup_restore',False) and self.recent_projects:QTimer.singleShot(200,self.reopen_last_project)
 def make_dashboard(self):
  page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(24,20,24,20);layout.setSpacing(12)
  title=QLabel('Your Projects');title.setObjectName('heading');layout.addWidget(title)
  description=QLabel('Pick up where you left off, or start with a new recording.');description.setObjectName('muted');layout.addWidget(description)
  actions=QHBoxLayout();actions.setSpacing(7);new=QPushButton('＋  New Project / Import Video');new.setObjectName('primary');new.clicked.connect(self.dashboard_new_project);actions.addWidget(new)
  op=QPushButton('📂  Open Project');op.clicked.connect(self.open_project);actions.addWidget(op);actions.addStretch();layout.addLayout(actions)
  recent_title=QLabel('Saved Projects');recent_title.setObjectName('heading');layout.addWidget(recent_title)
  self.dashboard_folder_label=QLabel('');self.dashboard_folder_label.setObjectName('muted');self.dashboard_folder_label.setWordWrap(True);layout.addWidget(self.dashboard_folder_label)
  self.dashboard_count_label=QLabel('');self.dashboard_count_label.setObjectName('dashboardCount');layout.addWidget(self.dashboard_count_label)
  filters=QHBoxLayout();self.dashboard_search=QLineEdit();self.dashboard_search.setPlaceholderText('Search projects in default folder…');self.dashboard_search.textChanged.connect(self.refresh_dashboard);filters.addWidget(self.dashboard_search,1)
  self.dashboard_sort=QComboBox();self.dashboard_sort.addItems(['Folder order','Last modified','Name (A–Z)']);self.dashboard_sort.currentIndexChanged.connect(self.refresh_dashboard);filters.addWidget(self.dashboard_sort);layout.addLayout(filters)
  self.dashboard_recent=QListWidget();self.dashboard_recent.setIconSize(__import__('PySide6.QtCore',fromlist=['QSize']).QSize(112,64));self.dashboard_recent.setSpacing(5);self.dashboard_recent.itemDoubleClicked.connect(self.dashboard_open_selected);layout.addWidget(self.dashboard_recent,1)
  self.dashboard_selection=QLabel('Select a project to see its details.');self.dashboard_selection.setObjectName('muted');self.dashboard_selection.setWordWrap(True);layout.addWidget(self.dashboard_selection)
  self.dashboard_recent.currentItemChanged.connect(self.dashboard_selection_changed)
  row=QHBoxLayout();open_selected=QPushButton('Open Selected');open_selected.clicked.connect(self.dashboard_open_selected);row.addWidget(open_selected)
  pin=QPushButton('Pin / Unpin');pin.clicked.connect(self.dashboard_toggle_pin);row.addWidget(pin)
  refresh=QPushButton('Refresh Folder');refresh.clicked.connect(self.refresh_dashboard);row.addWidget(refresh)
  row.addStretch();layout.addLayout(row)
  hint=QLabel('Only .csproj files currently in the default project folder are shown. Move a file out and refresh to remove it from the dashboard.');hint.setObjectName('muted');layout.addWidget(hint)
  self.stack.addWidget(page)
 def show_dashboard(self):
  self.refresh_dashboard();self.go(4)
 def dashboard_selection_changed(self,current,previous=None):
  if not hasattr(self,'dashboard_selection'):return
  path=current.data(Qt.UserRole) if current else None
  if not path:
   self.dashboard_selection.setText('Select a project to see its details.')
   return
  details,video=self.dashboard_project_details(path)
  self.dashboard_selection.setText('Selected: '+Path(path).name+'  |  '+details)

 def dashboard_project_details(self,path):
  project=Path(path)
  if not project.is_file():return '⚠ Project file missing',None
  try:
   data=json.loads(project.read_text(encoding='utf-8'))
   if not isinstance(data,dict):raise ValueError('Invalid project')
   duration=float(data.get('duration',0))
   candidates=data.get('candidates',[])
   count=1+sum(1 for c in candidates if isinstance(c,dict) and c.get('keep') and not c.get('rejected'))
   # The saved candidate list is the authoritative split source for this project.
   stamp=time.strftime('%Y-%m-%d %I:%M %p',time.localtime(project.stat().st_mtime))
   media=[]
   if data.get('video_relative'):media.append((project.parent/str(data['video_relative'])).resolve())
   if data.get('video'):media.append(Path(str(data['video'])).resolve())
   video=next((m for m in media if m.is_file()),None)
   warning='' if video else '  ⚠ Source video missing'
   return f'{count} clips  •  {fmt(duration)}  •  Modified {stamp}{warning}',video
  except (OSError,ValueError,TypeError,OverflowError):return '⚠ Unable to read project details',None
 def dashboard_thumbnail_path(self,path,video):
  if not video:return None
  try:
   stamp=str(video.stat().st_mtime_ns)
   key=hashlib.sha256((str(video)+stamp).encode('utf-8')).hexdigest()[:24]
   return APPDATA/'dashboard_thumbnails'/(key+'.jpg')
  except OSError:return None
 def refresh_dashboard(self,*args):
  if not hasattr(self,'dashboard_recent'):return
  selected=self.dashboard_recent.currentItem()
  selected_path=selected.data(Qt.UserRole) if selected else None
  self.dashboard_recent.clear()
  pinned=set(self.prefs.get('pinned_projects',[]))
  library=Path(self.prefs.get('project_library_folder','')).expanduser()
  if hasattr(self,'dashboard_folder_label'):
   self.dashboard_folder_label.setText('Project folder: '+str(library)+'  •  scans on startup and refresh')
  # The dashboard reflects only files physically present in the configured folder.
  # Recent-project history is kept separately for the File > Recent menu.
  paths=[]
  if library.is_dir():
   try:paths=[str(p.resolve()) for p in library.glob('*.csproj') if p.is_file()]
   except OSError:pass
  query=self.dashboard_search.text().casefold().strip()
  paths=[p for p in paths if query in (str(Path(p).name)+' '+str(Path(p).parent)).casefold()]
  mode=self.dashboard_sort.currentIndex()
  if mode==1:paths.sort(key=lambda p:Path(p).stat().st_mtime if Path(p).is_file() else -1,reverse=True)
  elif mode==2:paths.sort(key=lambda p:Path(p).name.casefold())
  paths.sort(key=lambda p:p not in pinned)
  self.dashboard_thumb_queue=[]
  for path in paths:
   details,video=self.dashboard_project_details(path)
   item=QListWidgetItem(('📌  ' if path in pinned else '')+Path(path).stem+'\n'+details+'\n'+str(Path(path).parent))
   item.setData(Qt.UserRole,path)
   item.setToolTip(path)
   thumbnail=self.dashboard_thumbnail_path(path,video)
   if thumbnail:
    if thumbnail.is_file():item.setIcon(QIcon(str(thumbnail)))
    else:self.dashboard_thumb_queue.append((path,str(video),str(thumbnail)))
   self.dashboard_recent.addItem(item)
   if path==selected_path:self.dashboard_recent.setCurrentItem(item)
  self.dashboard_count_label.setText(f'{len(paths)} project'+('' if len(paths)==1 else 's')+(' matching your search' if query else ' in this folder'))
  if not paths:self.dashboard_recent.addItem('No projects match your search.' if query else 'No saved projects yet — import a recording to get started.')
  if self.dashboard_recent.count() and paths and not self.dashboard_recent.currentItem():self.dashboard_recent.setCurrentRow(0)
  self.dashboard_next_thumbnail()
 def dashboard_next_thumbnail(self):
  if self.dashboard_thumb_proc is not None or not self.dashboard_thumb_queue:return
  path,video,destination=self.dashboard_thumb_queue.pop(0)
  try:Path(destination).parent.mkdir(parents=True,exist_ok=True)
  except OSError:return
  executable=tool('ffmpeg')
  if not executable:return
  proc=QProcess(self);self.dashboard_thumb_proc=proc
  proc.finished.connect(lambda code,status,p=path,d=destination,pr=proc:self.dashboard_thumbnail_done(p,d,pr))
  proc.errorOccurred.connect(lambda err,p=path,d=destination,pr=proc:self.dashboard_thumbnail_error(p,d,pr))
  proc.start(executable,['-hide_banner','-loglevel','error','-ss','2','-i',video,'-frames:v','1','-vf','scale=224:128:force_original_aspect_ratio=decrease','-y',destination])
 def dashboard_thumbnail_error(self,path,destination,proc):
  if proc.state()==QProcess.NotRunning:self.dashboard_thumbnail_done(path,destination,proc)
 def dashboard_thumbnail_done(self,path,destination,proc):
  if self.dashboard_thumb_proc is not proc:return
  self.dashboard_thumb_proc=None
  if Path(destination).is_file():
   for i in range(self.dashboard_recent.count()):
    item=self.dashboard_recent.item(i)
    if item.data(Qt.UserRole)==path:item.setIcon(QIcon(destination))
  proc.deleteLater()
  QTimer.singleShot(0,self.dashboard_next_thumbnail)
 def dashboard_toggle_pin(self):
  item=self.dashboard_recent.currentItem()
  if not item or not item.data(Qt.UserRole):return
  path=item.data(Qt.UserRole);pinned=list(self.prefs.get('pinned_projects',[]))
  if path in pinned:pinned.remove(path)
  else:pinned.append(path)
  self.prefs['pinned_projects']=pinned
  try:self.save_preferences(self.prefs)
  except OSError:pass
  self.refresh_dashboard()
 def dashboard_open_selected(self,*args):
  item=self.dashboard_recent.currentItem()
  if item and item.data(Qt.UserRole):self.open_project_path(item.data(Qt.UserRole))
 def dashboard_remove_selected(self):
  item=self.dashboard_recent.currentItem()
  if not item:return
  path=item.data(Qt.UserRole)
  if not path:return
  self.recent_projects=[p for p in self.recent_projects if p!=path]
  self.prefs['pinned_projects']=[p for p in self.prefs.get('pinned_projects',[]) if p!=path]
  self.prefs['recent_projects']=list(self.recent_projects)
  try:self.save_preferences(self.prefs)
  except OSError:pass
  self.refresh_recent_menu();self.refresh_dashboard()
  self.status.setText('Removed from recent projects (project file was not deleted)')
 def dashboard_new_project(self):
  if self.video:
   self.close_project()
   if self.video:return
  self.go(0);self.choose()
 def make_import(self):
  page=QWidget();lay=QVBoxLayout(page);lay.setSpacing(15);lay.setContentsMargins(24,20,24,24)
  title=QLabel('Import & Scan');title.setObjectName('importHeading');lay.addWidget(title)
  sub=QLabel('Start with a recording, then find commercial boundaries automatically.')
  sub.setObjectName('muted');sub.setWordWrap(True);lay.addWidget(sub)
  self.drop=DropZone();self.drop.setMinimumHeight(215)
  self.drop.pick.clicked.connect(self.choose);self.drop.dropped.connect(self.load_video)
  lay.addWidget(self.drop)
  self.import_file_heading=QLabel('RECORDING DETAILS');self.import_file_heading.setObjectName('dashboardCount');lay.addWidget(self.import_file_heading)
  self.info=QLabel('No recording loaded');self.info.setObjectName('importFileInfo');self.info.setWordWrap(True)
  lay.addWidget(self.info)
  self.import_file_path=QLabel('Drag a video into the area above, or browse to select a file.')
  self.import_file_path.setObjectName('muted');self.import_file_path.setWordWrap(True);self.import_file_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
  lay.addWidget(self.import_file_path)
  scan_group=QGroupBox('Recording tools');self.import_scan_layout=QVBoxLayout(scan_group)
  self.import_scan_layout.setContentsMargins(16,18,16,16);self.import_scan_layout.setSpacing(10)
  lay.addWidget(scan_group);self.import_scan_group=scan_group
  fresh=QPushButton('↺  Start Over with This Recording')
  fresh.setToolTip('Clear all accepted, rejected, and suggested cuts for this recording; keep the video loaded')
  fresh.clicked.connect(self.fresh_start_cuts);self.import_scan_layout.addWidget(fresh)
  self.import_scan_group.setVisible(False)
  row=QHBoxLayout();row.addStretch()
  b=QPushButton('Open Timeline  →');b.setObjectName('primary')
  b.setToolTip('Go to the Timeline workspace to inspect and edit cuts')
  b.clicked.connect(lambda:self.go(2));row.addWidget(b);lay.addLayout(row)
  lay.addStretch(1)
  scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame)
  scroll.setWidget(page);self.stack.addWidget(scroll)
 def fresh_start_cuts(self):
  if not self.video:return
  if self.busy:
   QMessageBox.information(self,'Operation in progress','Wait for the current scan or export to finish before resetting cuts.');return
  if not self.candidates and not self.cuts:
   self.status.setText('No cuts to clear');return
  reply=QMessageBox.question(self,'Fresh Start Cuts',
   'Remove ALL accepted cuts, automatic suggestions, and rejected candidates for this recording?\n\n'
   'The recording and exported files are not changed. You can use Timeline Undo to restore the cut decisions.',
   QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
  if reply!=QMessageBox.Yes:return
  self.timeline_snapshot()
  self.candidates=[];self.cuts=[];self.scan_times=[]
  self.auto_black_intervals=[];self.auto_visual_times=[];self.auto_silence_intervals=[]
  self.timeline_view.selected=None
  self.active_queue='scanned'
  self.sync_candidates(queue='scanned')
  self.save_recovery()
  self.reset_export_preview();self.populate_gallery()
  self.status.setText('All cuts cleared — ready for a fresh scan (Timeline Undo restores cuts)')
 def make_review(self):
  page=QWidget();lay=QVBoxLayout(page);lay.setSpacing(11)
  legend=QLabel('REVIEW GUIDE   •   Green: accepted   •   Purple: accepted low confidence   •   Blue: manual   •   Amber: suggested   •   Gray: rejected')
  legend.setObjectName('muted');legend.setWordWrap(True);lay.addWidget(legend)
  self.review_workspace=QSplitter(Qt.Vertical)
  self.review_workspace.setChildrenCollapsible(False)
  self.review_workspace.setHandleWidth(10)
  self.review_workspace.setToolTip('Drag this divider to resize the cut previews and review lists')
  monitor=QFrame();monitor.setObjectName('previewPanel');preview_layout=QVBoxLayout(monitor);preview_layout.setSpacing(6)
  self.review_video=QLabel('Load a recording, then select a cut to compare its frames');self.review_video.setAlignment(Qt.AlignCenter);self.review_video.setObjectName('muted');preview_layout.addWidget(self.review_video)
  previews=QHBoxLayout();previews.setSpacing(14)
  self.before_preview=QLabel('Before cut\nNo preview');self.after_preview=QLabel('After cut\nNo preview')
  for caption,widget in [('BEFORE CUT',self.before_preview),('AFTER CUT',self.after_preview)]:
   column=QVBoxLayout();heading=QLabel(caption);heading.setObjectName('muted');column.addWidget(heading)
   widget.setObjectName('framePreview');widget.setAlignment(Qt.AlignCenter);widget.setMinimumHeight(150);widget.setMinimumWidth(220)
   column.addWidget(widget,1);previews.addLayout(column,1)
  preview_layout.addLayout(previews,1);self.review_workspace.addWidget(monitor)
  advanced=QFrame();advanced_outer=QVBoxLayout(advanced);advanced_outer.setContentsMargins(0,0,0,0)
  advanced_toggle=QPushButton('▸  Advanced detection controls');advanced_toggle.setCheckable(True);advanced_outer.addWidget(advanced_toggle)
  advanced_body=QWidget();advanced_layout=QVBoxLayout(advanced_body);advanced_outer.addWidget(advanced_body)
  advanced_body.setVisible(False)
  advanced_toggle.toggled.connect(lambda expanded: (advanced_body.setVisible(expanded),advanced_toggle.setText(('▾' if expanded else '▸')+'  Advanced detection controls')))
  scanrow=QHBoxLayout()
  scanrow.addWidget(QLabel('Scene threshold'))
  self.threshold=QDoubleSpinBox();self.threshold.setRange(.01,.99);self.threshold.setSingleStep(.05);self.threshold.setValue(.35);scanrow.addWidget(self.threshold)
  scanrow.addWidget(QLabel('Minimum gap (s)'))
  self.gap=QDoubleSpinBox();self.gap.setRange(0,60);self.gap.setValue(.5);scanrow.addWidget(self.gap)
  advanced_layout.addLayout(scanrow)
  self.scan_btn=QPushButton('Scan Recording && Find Cuts');self.scan_btn.setObjectName('primary');self.scan_btn.setToolTip('Analyze the recording for commercial boundaries using scene, black-frame and audio evidence');self.scan_btn.clicked.connect(self.scan_native);self.import_scan_layout.addWidget(self.scan_btn)
  smartrow=QHBoxLayout();smartrow.addWidget(QLabel('Sensitivity:'))
  self.detection_sensitivity=QComboBox();self.detection_sensitivity.addItems(['Conservative','Balanced','Aggressive']);self.detection_sensitivity.setCurrentText('Balanced');smartrow.addWidget(self.detection_sensitivity)
  smartrow.addWidget(QLabel('Min clip (s):'));self.detection_min=QSpinBox();self.detection_min.setRange(2,180);self.detection_min.setValue(8);smartrow.addWidget(self.detection_min)
  smartrow.addWidget(QLabel('Max clip (s):'));self.detection_max=QSpinBox();self.detection_max.setRange(10,600);self.detection_max.setValue(90);smartrow.addWidget(self.detection_max)
  self.detection_compare_btn=QPushButton('Compare Modes');self.detection_compare_btn.clicked.connect(self.compare_detection_modes);smartrow.addWidget(self.detection_compare_btn)
  advanced_layout.addLayout(smartrow)
  profilebar=QHBoxLayout();profilebar.addWidget(QLabel('Detection profile'))
  self.profile_picker=QComboBox();self.profile_picker.setMinimumWidth(155);profilebar.addWidget(self.profile_picker,1)
  self.profile_picker.currentTextChanged.connect(self.apply_detection_profile)
  profile_edit=QPushButton('Edit / Save Profiles…');profile_edit.clicked.connect(self.edit_detection_profiles);profilebar.addWidget(profile_edit)
  self.import_scan_layout.addLayout(profilebar)
  self.import_scan_layout.addWidget(advanced)
  self.populate_detection_profiles()
  self.auto_btn=QPushButton('Rescan && Refresh Suggestions');self.auto_btn.clicked.connect(self.auto_suggest);self.auto_btn.setToolTip('Run the same combined scan again to refresh suggestions');self.import_scan_layout.addWidget(self.auto_btn)
  self.cancel_auto_btn=QPushButton('Cancel Auto Detection');self.cancel_auto_btn.setEnabled(False);self.cancel_auto_btn.clicked.connect(self.cancel_auto);self.import_scan_layout.addWidget(self.cancel_auto_btn)
  diagnostic_btn=QPushButton('Inspect Detected Boundary…');diagnostic_btn.setToolTip('Show raw black intervals and nearby cut suggestions at a timestamp after Auto Suggest Cuts');diagnostic_btn.clicked.connect(self.inspect_detected_boundary);self.import_scan_layout.addWidget(diagnostic_btn)
  self.auto_progress=QProgressBar();self.auto_progress.setRange(0,100);self.auto_progress.setValue(0);self.auto_progress.setFormat('%p% analyzed');self.auto_progress.setVisible(False);self.import_scan_layout.addWidget(self.auto_progress)
  self.auto_progress_detail=QLabel('');self.auto_progress_detail.setObjectName('muted');self.auto_progress_detail.setVisible(False);self.import_scan_layout.addWidget(self.auto_progress_detail)
  feedback=QGroupBox('Detection Feedback — review statistics (not verified accuracy)')
  feedback_layout=QVBoxLayout(feedback)
  self.detection_feedback_summary=QLabel('Load a recording and review candidate cuts to see feedback statistics.')
  self.detection_feedback_summary.setWordWrap(True);self.detection_feedback_summary.setObjectName('muted')
  feedback_layout.addWidget(self.detection_feedback_summary)
  self.detection_feedback_comparison=QLabel('Mode comparison becomes available after Auto Suggest Cuts.')
  self.detection_feedback_comparison.setWordWrap(True);self.detection_feedback_comparison.setObjectName('muted')
  feedback_layout.addWidget(self.detection_feedback_comparison)
  refresh_feedback=QPushButton('Refresh Detection Feedback')
  refresh_feedback.clicked.connect(self.update_detection_feedback)
  feedback_layout.addWidget(refresh_feedback)
  reports=QFrame();reports_outer=QVBoxLayout(reports);reports_outer.setContentsMargins(0,0,0,0)
  reports_toggle=QPushButton('▸  Detection feedback and reports');reports_toggle.setCheckable(True);reports_outer.addWidget(reports_toggle)
  reports_body=QWidget();reports_layout=QVBoxLayout(reports_body);reports_outer.addWidget(reports_body)
  reports_body.setVisible(False)
  reports_toggle.toggled.connect(lambda expanded: (reports_body.setVisible(expanded),reports_toggle.setText(('▾' if expanded else '▸')+'  Detection feedback and reports')))
  reports_layout.addWidget(feedback)
  self.report_btn=QPushButton('Save Detection Report (CSV)');self.report_btn.clicked.connect(self.save_detection_report);self.report_btn.setToolTip('Export review totals, mode comparison, and per-candidate decisions as CSV');reports_layout.addWidget(self.report_btn);self.import_scan_layout.addWidget(reports)
  progressrow=QHBoxLayout();self.scan_progress=QProgressBar();self.scan_progress.setRange(0,100);self.scan_progress.setValue(0);self.scan_progress.setFormat('%p% scanned');progressrow.addWidget(self.scan_progress,1)
  self.scan_detail=QLabel('Not scanning');self.scan_detail.setObjectName('muted');progressrow.addWidget(self.scan_detail);self.import_scan_layout.addLayout(progressrow)
  review_lists_panel=QFrame();review_lists_layout=QVBoxLayout(review_lists_panel);review_lists_layout.setContentsMargins(2,4,2,2)
  queues=QHBoxLayout();queues.setSpacing(12)
  left=QVBoxLayout();left.addWidget(QLabel('SCANNED SCENES  •  Suggestions & decisions'))
  self.candidate_list=QListWidget();self.candidate_list.setMinimumHeight(130);self.candidate_list.setAlternatingRowColors(True);self.candidate_list.setToolTip('Select a detected scene to inspect, accept, reject, or adjust it. Double-click to accept.')
  self.candidate_list.currentRowChanged.connect(lambda row:self.queue_selected('scanned',row))
  self.candidate_list.itemDoubleClicked.connect(self.accept_double_clicked_candidate)
  self.remove_review_shortcut=QShortcut(QKeySequence(Qt.Key_Delete),self.candidate_list)
  self.remove_review_shortcut.setKey(QKeySequence())  # Delete is routed centrally
  left.addWidget(self.candidate_list);left.addWidget(QLabel('Double-click a suggestion to accept it. Rejected scenes remain available.'))
  queues.addLayout(left,2)
  right=QVBoxLayout();right.addWidget(QLabel('ACCEPTED CUTS  •  Export boundaries'))
  self.accepted_list=QListWidget();self.accepted_list.setMinimumHeight(130);self.accepted_list.setAlternatingRowColors(True);self.accepted_list.setToolTip('Accepted boundaries used to divide exported clips. Select one to inspect or adjust.')
  self.accepted_list.currentRowChanged.connect(lambda row:self.queue_selected('accepted',row))
  self.delete_shortcut=QShortcut(QKeySequence(Qt.Key_Delete),self.accepted_list)
  self.delete_shortcut.setKey(QKeySequence())  # Delete is routed centrally
  right.addWidget(self.accepted_list);right.addWidget(QLabel('Only accepted boundaries affect clip exports.'))
  queues.addLayout(right,1);review_lists_layout.addLayout(queues,1)
  self.review_workspace.addWidget(review_lists_panel)
  self.review_workspace.setStretchFactor(0,3);self.review_workspace.setStretchFactor(1,2)
  stored=self.prefs.get('review_workspace_sizes',[380,260])
  if isinstance(stored,list) and len(stored)==2 and all(isinstance(x,int) and x>0 for x in stored):
   self.review_workspace.setSizes(stored)
  else:self.review_workspace.setSizes([380,260])
  self.review_workspace.splitterMoved.connect(lambda *_:self.save_ui_preference('review_workspace_sizes',self.review_workspace.sizes()))
  lay.addWidget(self.review_workspace,1)
  self.active_queue='scanned'
  actions=QHBoxLayout()
  for label,method in [('✓ Accept',self.accept_cut),('✕ Reject',self.reject_cut),('◀ Earlier',lambda:self.nudge_cut(-1)),('Later ▶',lambda:self.nudge_cut(1)),('▶ Preview From Cut',self.preview_review)]:
   btn=QPushButton(label);btn.clicked.connect(method);btn.setToolTip('Play from the exact selected cut boundary' if 'Preview' in label else 'Apply this action to the currently selected cut');actions.addWidget(btn)
  actions.addWidget(QLabel('Move by'))
  self.move_step=QComboBox();self.move_step.addItems(['1 frame','5 frames','0.5 seconds','1 second','5 seconds','10 seconds']);actions.addWidget(self.move_step)
  remove_review=QPushButton('Delete Suggestion');remove_review.setToolTip('Permanently remove the selected scanned suggestion (accepted cuts are protected)');remove_review.clicked.connect(self.delete_review_candidate);actions.addWidget(remove_review)
  clear_review=QPushButton('Clear Pending');clear_review.setToolTip('Remove all unaccepted scanned candidates, keeping accepted export cuts');clear_review.clicked.connect(self.clear_unaccepted_review_candidates);actions.addWidget(clear_review)
  lay.addLayout(actions)
  self.review_summary=QLabel('Load a recording to see saved accepted cuts.');self.review_summary.setObjectName('muted');self.review_summary.setWordWrap(True);lay.addWidget(self.review_summary)
  row=QHBoxLayout()
  refresh=QPushButton('Reload Saved Cuts');refresh.clicked.connect(self.read_recovery);row.addWidget(refresh)
  clear=QPushButton('Start Fresh / Clear Recovery');clear.clicked.connect(self.clear_video_recovery);row.addWidget(clear)
  close=QPushButton('Close Project');close.clicked.connect(self.close_project);row.addWidget(close)
  row.addStretch();nextb=QPushButton('Continue to Export  →');nextb.clicked.connect(lambda:self.go(3));row.addWidget(nextb);lay.addLayout(row)
  scroll=QScrollArea()
  scroll.setWidgetResizable(True)
  scroll.setFrameShape(QFrame.NoFrame)
  scroll.setWidget(page)
  self.stack.addWidget(scroll)
 def builtin_detection_profiles(self):
  return {
   'Balanced':{'sensitivity':'Balanced','scene':0.35,'gap':0.5,'minimum':8,'maximum':90,'black':0.12,'silence':-32},
   'VHS Commercials':{'sensitivity':'Balanced','scene':0.42,'gap':0.6,'minimum':8,'maximum':120,'black':0.19,'silence':-27},
   'Digital Recordings':{'sensitivity':'Conservative','scene':0.30,'gap':0.4,'minimum':8,'maximum':90,'black':0.08,'silence':-38},
   'Cartoon Breaks':{'sensitivity':'Aggressive','scene':0.38,'gap':0.3,'minimum':4,'maximum':90,'black':0.13,'silence':-32},
  }
 def all_detection_profiles(self):
  profiles=self.builtin_detection_profiles()
  custom=self.prefs.get('detection_profiles',{})
  if isinstance(custom,dict):
   for name,values in custom.items():
    if isinstance(name,str) and isinstance(values,dict) and name not in profiles:profiles[name]=values
  return profiles
 def populate_detection_profiles(self):
  name=self.prefs.get('active_detection_profile','Balanced')
  self.profile_picker.blockSignals(True);self.profile_picker.clear();self.profile_picker.addItems(list(self.all_detection_profiles()))
  self.profile_picker.setCurrentText(name if name in self.all_detection_profiles() else 'Balanced')
  self.profile_picker.blockSignals(False)
  self.apply_detection_profile(self.profile_picker.currentText())
 def apply_detection_profile(self,name):
  data=self.all_detection_profiles().get(name)
  if not data:return
  self.detection_sensitivity.setCurrentText(str(data.get('sensitivity','Balanced')))
  self.threshold.setValue(float(data.get('scene',.35)))
  self.gap.setValue(float(data.get('gap',.5)))
  self.detection_min.setValue(int(data.get('minimum',8)))
  self.detection_max.setValue(int(data.get('maximum',90)))
  self.active_black_threshold=float(data.get('black',.12))
  self.active_silence_db=int(data.get('silence',-32))
  self.prefs['active_detection_profile']=name
  self.save_preferences(self.prefs)
 def edit_detection_profiles(self):
  dialog=QDialog(self);dialog.setWindowTitle('Custom detection profile');dialog.resize(460,390)
  layout=QVBoxLayout(dialog);layout.addWidget(QLabel('Create a profile from the current detection settings.'))
  form=QFormLayout();name=QLineEdit();name.setPlaceholderText('e.g. My VHS Captures');form.addRow('Profile name',name)
  scene=QDoubleSpinBox();scene.setRange(.01,.99);scene.setSingleStep(.01);scene.setValue(self.threshold.value());form.addRow('Scene threshold',scene)
  gap=QDoubleSpinBox();gap.setRange(0,60);gap.setValue(self.gap.value());form.addRow('Minimum scene gap (s)',gap)
  black=QDoubleSpinBox();black.setRange(.01,.95);black.setSingleStep(.01);black.setValue(getattr(self,'active_black_threshold',.12));form.addRow('Black pixel threshold',black)
  silence=QSpinBox();silence.setRange(-80,-5);silence.setValue(getattr(self,'active_silence_db',-32));form.addRow('Silence threshold (dB)',silence)
  minimum=QSpinBox();minimum.setRange(2,180);minimum.setValue(self.detection_min.value());form.addRow('Minimum clip (s)',minimum)
  maximum=QSpinBox();maximum.setRange(10,600);maximum.setValue(self.detection_max.value());form.addRow('Maximum clip (s)',maximum)
  sensitivity=QComboBox();sensitivity.addItems(['Conservative','Balanced','Aggressive']);sensitivity.setCurrentText(self.detection_sensitivity.currentText());form.addRow('Sensitivity',sensitivity)
  layout.addLayout(form)
  buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);layout.addWidget(buttons);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
  if dialog.exec()!=QDialog.Accepted:return
  label=name.text().strip()
  if not label or label in self.builtin_detection_profiles():
   QMessageBox.warning(self,'Invalid name','Enter a unique profile name (built-in profiles cannot be overwritten).');return
  custom=self.prefs.setdefault('detection_profiles',{})
  custom[label]={'scene':scene.value(),'gap':gap.value(),'black':black.value(),'silence':silence.value(),'minimum':minimum.value(),'maximum':maximum.value(),'sensitivity':sensitivity.currentText()}
  self.prefs['active_detection_profile']=label;self.save_preferences(self.prefs);self.populate_detection_profiles()
  self.status.setText(f'Detection profile saved: {label}')
 def make_timeline(self):
  page=QWidget();lay=QVBoxLayout(page);lay.setSpacing(6);lay.setContentsMargins(8,6,8,6)
  self.timeline_video=QVideoWidget();self.timeline_video.setMinimumHeight(110);self.timeline_video.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
  self.timeline_preview_splitter=QSplitter(Qt.Horizontal)
  self.timeline_preview_splitter.setChildrenCollapsible(False)
  # Put the Before Frame panel on the left, with live playback on the right.
  self.cut_inspector_panel=QFrame();self.cut_inspector_panel.setObjectName('previewPanel')
  self.cut_inspector_panel.setMinimumWidth(235)
  self.cut_inspector_panel.setMaximumWidth(430)
  self.cut_inspector_panel.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Expanding)
  inspector=QVBoxLayout(self.cut_inspector_panel)
  inspector.setContentsMargins(9,8,9,8)
  inspector.setSpacing(6)
  inspector_title=QLabel('CUT INSPECTOR  •  Boundaries')
  inspector_title.setToolTip('Accepted cuts of any confidence, plus pending Medium/High suggestions. Unaccepted Low suggestions remain in Review.')
  inspector.addWidget(inspector_title)
  self.inspector_progress=QLabel('No suggested cuts yet');self.inspector_progress.setWordWrap(True);self.inspector_progress.setObjectName('muted');inspector.addWidget(self.inspector_progress)
  self.inspector_list=QListWidget();self.inspector_list.setMinimumWidth(200);self.inspector_list.setMinimumHeight(72)
  self.inspector_list.setToolTip('All accepted cuts, including Low confidence, plus pending Medium/High suggestions. Select to inspect or edit.')
  self.inspector_list.setAlternatingRowColors(True)
  self.inspector_list.setSpacing(5)
  # Theme-aware list styling: do not override each item's status foreground.
  self.inspector_list.setObjectName('cutInspectorList')
  self.inspector_list.setFocusPolicy(Qt.StrongFocus)
  self.inspector_list.setUniformItemSizes(True)
  self.inspector_list.currentRowChanged.connect(self.inspector_select_cut)
  # The existing window-level Delete shortcut handles this list; avoid ambiguous shortcuts.
  # Keep the cut list tall and place its actions in a narrow right column.
  list_actions=QHBoxLayout();list_actions.setSpacing(6)
  list_actions.addWidget(self.inspector_list,1)
  action_column=QVBoxLayout();action_column.setSpacing(4)
  accept=QPushButton('Accept');accept.setObjectName('primary');accept.clicked.connect(lambda:self.inspector_decide(True))
  reject=QPushButton('Reject');reject.clicked.connect(lambda:self.inspector_decide(False))
  delete_suggestion=QPushButton('Delete')
  delete_suggestion.setToolTip('Remove the selected cut (Delete key). Accepted cuts are removed from Timeline and Export; Undo restores them.')
  delete_suggestion.clicked.connect(self.inspector_delete_selected_cut)
  for button in (accept,reject,delete_suggestion):
   button.setMinimumWidth(65);button.setMaximumWidth(90)
   action_column.addWidget(button)
  action_column.addStretch(1)
  list_actions.addLayout(action_column)
  inspector.addLayout(list_actions,1)
  self.inspector_detail=QLabel('Select a cut to inspect its detection evidence.')
  self.inspector_detail.setWordWrap(True);inspector.addWidget(self.inspector_detail)
  # Adjacent previous-frame preview; live player remains the current-frame view.
  self.after_frame_panel=QFrame();self.after_frame_panel.setObjectName('previewPanel')
  after_layout=QVBoxLayout(self.after_frame_panel)
  after_heading=QLabel('BEFORE CUT  •  Previous frame');after_heading.setAlignment(Qt.AlignCenter)
  after_layout.addWidget(after_heading)
  self.after_frame_picture=QLabel('Select a split marker')
  self.after_frame_picture.setAlignment(Qt.AlignCenter)
  self.after_frame_picture.installEventFilter(self)
  self.after_frame_picture.setMinimumSize(185,105)
  self.after_frame_picture.setStyleSheet('background:#1b2836;color:#b7c6d4;border:1px solid #405168;border-radius:5px;')
  after_layout.addWidget(self.after_frame_picture,1)
  self.split_preview_title=QLabel('Select a split marker');self.split_preview_title.setWordWrap(True)
  after_layout.addWidget(self.split_preview_title)
  self.timeline_preview_splitter.addWidget(self.after_frame_panel)
  self.timeline_video_stack=QStackedWidget()
  self.timeline_video_stack.addWidget(self.timeline_video)
  self.timeline_still=QLabel('Select a cut to preview')
  self.timeline_still.setAlignment(Qt.AlignCenter)
  self.timeline_still.installEventFilter(self)
  self.timeline_still.setStyleSheet('background:#101820;color:#b7c6d4;')
  self.timeline_video_stack.addWidget(self.timeline_still)
  self.timeline_still_proc=None
  self.timeline_still_token=0
  self.timeline_still_cache={}
  self.timeline_preview_splitter.addWidget(self.timeline_video_stack)
  self.timeline_preview_splitter.addWidget(self.cut_inspector_panel)
  # Prioritize two resizable previews while retaining the inspector on the right.
  self.timeline_preview_splitter.setMinimumHeight(215)
  self.timeline_preview_splitter.setHandleWidth(12)
  self.timeline_preview_splitter.setToolTip('Drag the dividers to resize the Before Cut preview, Current Video, and right-side Cut Inspector')
  self.timeline_preview_splitter.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
  widths=self.prefs.get('cut_inspector_widths',[790,290])
  if not isinstance(widths,list) or len(widths) not in (2,3) or not all(isinstance(x,int) and x>0 for x in widths):widths=[790,290]
  # Existing saved widths used the previous live/before/inspector order.
  self.timeline_preview_splitter.setStretchFactor(0,1)
  self.timeline_preview_splitter.setStretchFactor(1,1)
  self.timeline_preview_splitter.setStretchFactor(2,0)
  if len(widths)==3:
   self.timeline_preview_splitter.setSizes(widths)
  else:
   self.timeline_preview_splitter.setSizes([500,500,270])
  self.timeline_preview_splitter.splitterMoved.connect(lambda *_:self.save_ui_preference('cut_inspector_widths',self.timeline_preview_splitter.sizes()))
  self.cut_inspector_panel.setVisible(bool(self.prefs.get('cut_inspector_visible',True)))
  inspector_toggle=QPushButton('Hide Cut Inspector' if self.cut_inspector_panel.isVisible() else 'Show Cut Inspector')
  inspector_toggle.setToolTip('Show or hide the right-side Cut Inspector to give the video previews more room')
  inspector_toggle.clicked.connect(lambda:self.toggle_cut_inspector(inspector_toggle))
  inspector_heading=QHBoxLayout();inspector_heading.addWidget(QLabel('VIDEO PREVIEWS  •  Drag dividers to resize'));inspector_heading.addSpacing(18);inspector_heading.addWidget(QLabel('Snap:'));inspector_heading.addStretch();inspector_heading.addWidget(inspector_toggle)
  lay.addLayout(inspector_heading);lay.addWidget(self.timeline_preview_splitter,1)
  self.timeline_player=QMediaPlayer(self);self.timeline_audio=QAudioOutput(self);self.timeline_player.setAudioOutput(self.timeline_audio);self.timeline_player.setVideoOutput(self.timeline_video)
  self.timeline_media_path=None
  self.timeline_thumbs=[];self.timeline_thumb_process=None;self.timeline_thumb_index=0;self.timeline_thumb_token=0
  self.timeline_thumb_video=None;self.timeline_thumb_duration=0;self.timeline_thumb_range=None;self.timeline_zoom_factor=1;self.timeline_pan_fraction=0
  self.timeline_waveform=[];self.timeline_wave_process=None;self.timeline_wave_token=0;self.timeline_wave_buffer=bytearray()
  self.timeline_wave_cache={};self.timeline_thumb_cache={};self.timeline_wave_key=None
  self.timeline_refresh_timer=QTimer(self);self.timeline_refresh_timer.setSingleShot(True);self.timeline_refresh_timer.setInterval(260);self.timeline_refresh_timer.timeout.connect(self.timeline_start_thumbnails)
  self.timeline_snap_enabled=True;self.timeline_smart_snap_enabled=False;self.timeline_wheel_anchor=None
  self.timeline_motion_preview_end=None
  self.timeline_motion_preview_started=False
  self.timeline_motion_preview_timer=QTimer(self)
  self.timeline_motion_preview_timer.setInterval(40)
  self.timeline_motion_preview_timer.timeout.connect(self.timeline_check_motion_preview)
  self.timeline_pending_inspector_seek=None
  # When the media backend is paused, the FFmpeg still must follow seeks.
  # Otherwise it remains pinned to the first Inspector selection until Play.
  self.timeline_paused_still_timer=QTimer(self)
  self.timeline_paused_still_timer.setSingleShot(True)
  self.timeline_paused_still_timer.setInterval(85)
  self.timeline_paused_still_timer.timeout.connect(self.timeline_refresh_paused_still)
  self.timeline_player.mediaStatusChanged.connect(self.timeline_inspector_media_ready)
  self.timeline_player.positionChanged.connect(self.timeline_position_changed)
  self.timeline_player.playbackStateChanged.connect(lambda state:self.timeline_play.setText('Pause' if state==QMediaPlayer.PlayingState else 'Play'))
  self.timeline_player.playbackStateChanged.connect(lambda state:self.timeline_video_stack.setCurrentIndex(0) if state==QMediaPlayer.PlayingState else None)
  self.timeline_wave_mode=QComboBox();self.timeline_wave_mode.addItems(['On timeline (inside clips)','Above timeline (separate track)','Off'])
  self.timeline_wave_mode.setCurrentIndex(max(0,min(2,int(self.prefs.get('timeline_wave_mode',0)))))
  self.timeline_wave_mode.currentIndexChanged.connect(self.timeline_wave_mode_changed)
  self.timeline_view=CutTimeline(self);self.timeline_view.setFixedHeight(330 if self.timeline_wave_mode.currentIndex()==1 else 190);lay.addWidget(self.timeline_view)
  zoomrow=QHBoxLayout();zoomrow.addWidget(QLabel('TIMELINE  •  Zoom'))
  self.timeline_zoom=QSlider(Qt.Horizontal);self.timeline_zoom.setToolTip('Zoom in on the Timeline (mouse wheel also works over the Timeline)');self.timeline_zoom.setRange(0,6);self.timeline_zoom.setValue(0);self.timeline_zoom.setFixedWidth(170);self.timeline_zoom.valueChanged.connect(self.timeline_zoom_changed);zoomrow.addWidget(self.timeline_zoom)
  self.timeline_zoom_label=QLabel('1×');zoomrow.addWidget(self.timeline_zoom_label)
  fit=QPushButton('Fit Video');fit.setToolTip('Reset zoom to show the entire recording');fit.clicked.connect(lambda:self.timeline_zoom.setValue(0));zoomrow.addWidget(fit)
  self.timeline_visible_label=QLabel('');self.timeline_visible_label.setMinimumWidth(155)
  zoomrow.addWidget(self.timeline_visible_label)
  zoomrow.addWidget(QLabel('Scroll'))
  self.timeline_pan=QSlider(Qt.Horizontal);self.timeline_pan.setToolTip('Pan left or right through the zoomed Timeline');self.timeline_pan.setRange(0,1000);self.timeline_pan.setValue(0);self.timeline_pan.valueChanged.connect(self.timeline_pan_changed);zoomrow.addWidget(self.timeline_pan,1)
  lay.addLayout(zoomrow)
  navrow=QHBoxLayout()
  previous_cut=QPushButton('◀ Previous Split');previous_cut.setToolTip('Jump to the preceding accepted split marker')
  previous_cut.clicked.connect(lambda:self.timeline_navigate_marker(-1));navrow.addWidget(previous_cut)
  next_cut=QPushButton('Next Split ▶');next_cut.setToolTip('Jump to the next accepted split marker')
  next_cut.clicked.connect(lambda:self.timeline_navigate_marker(1));navrow.addWidget(next_cut)
  navrow.addStretch()
  self.timeline_marker_count=QLabel('');navrow.addWidget(self.timeline_marker_count)
  lay.addLayout(navrow)
  jump=QHBoxLayout();jump.addWidget(QLabel('Clip'))
  self.timeline_clip_select=QComboBox();self.timeline_clip_select.setToolTip('Jump to a clip without changing its boundaries');self.timeline_clip_select.setMinimumWidth(220);self.timeline_clip_select.currentIndexChanged.connect(self.timeline_clip_changed);jump.addWidget(self.timeline_clip_select,1)
  self.timeline_tools=QWidget()
  clip_tools_layout=QVBoxLayout(self.timeline_tools);clip_tools_layout.setContentsMargins(4,4,4,4);clip_tools_layout.setSpacing(4)
  clip_tools_layout.addLayout(jump)
  naming=QHBoxLayout();naming.addWidget(QLabel('Selected clip name'))
  self.timeline_clip_name=QLineEdit();self.timeline_clip_name.setPlaceholderText('e.g. Cartoon Network Promo')
  self.timeline_clip_name.setToolTip('Name for the selected clip; used as its exported MP4 filename. Leave blank for Commercial_001.mp4, etc.')
  naming.addWidget(self.timeline_clip_name,1)
  self.timeline_clip_name.editingFinished.connect(self.timeline_save_clip_name)
  suggest=QPushButton('Suggest Name');suggest.setToolTip('Fill a simple name from the recording title and clip number; edit it as desired')
  suggest.clicked.connect(self.timeline_suggest_clip_name);naming.addWidget(suggest)
  clip_tools_layout.addLayout(naming)
  organizer=QGroupBox('Visual Clip Organizer')
  organizer_layout=QVBoxLayout(organizer)
  organizer_note=QLabel('Click to jump • Ctrl+Click to select multiple • Shift+Click to select a range • Drag to reorder. Source cuts stay unchanged.')
  organizer_note.setObjectName('muted');organizer_layout.addWidget(organizer_note)
  self.clip_organizer_scroll=QScrollArea();self.clip_organizer_scroll.setWidgetResizable(True)
  self.clip_organizer_scroll.setMinimumHeight(110)
  self.clip_organizer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
  self.clip_organizer_inner=QWidget();self.clip_organizer_layout=QHBoxLayout(self.clip_organizer_inner)
  self.clip_organizer_layout.setContentsMargins(6,6,6,6)
  self.clip_organizer_scroll.setWidget(self.clip_organizer_inner)
  organizer_layout.addWidget(self.clip_organizer_scroll)
  batch_row=QHBoxLayout()
  self.batch_prefix=QLineEdit();self.batch_prefix.setPlaceholderText('Prefix for selected clips (e.g. Cartoon Network)')
  batch_row.addWidget(self.batch_prefix,1)
  for label,handler in [('Apply Prefix',self.organizer_batch_prefix),('Include in Export',lambda:self.organizer_batch_include(True)),('Exclude from Export',lambda:self.organizer_batch_include(False)),('Clear Selection',self.organizer_clear_selection)]:
   btn=QPushButton(label);btn.clicked.connect(handler);batch_row.addWidget(btn)
  organizer_layout.addLayout(batch_row)
  self.organizer_selection_label=QLabel('0 clips selected');organizer_layout.addWidget(self.organizer_selection_label)
  organizer.setVisible(bool(self.prefs.get('timeline_organizer_visible',False)))
  self.timeline_organizer_group=organizer
  self.clip_organizer_items=[];self.clip_organizer_cache={}
  self.organizer_selected=set();self.organizer_anchor=None;self.batch_excluded=set()
  self.clip_organizer_process=None;self.clip_organizer_token=0
  self.clip_organizer_queue=[];self.clip_organizer_signature=None
  # Two clearly labeled rows keep playback and editing actions distinct.
  playback_controls=QHBoxLayout()
  playback_controls.setSpacing(7)
  playback_controls.addWidget(QLabel('PLAYBACK'))
  self.timeline_play=QPushButton('Play');self.timeline_play.setToolTip('Play or pause the current recording')
  self.timeline_play.clicked.connect(self.timeline_toggle);playback_controls.addWidget(self.timeline_play)
  prev_btn=QPushButton('◀ Previous Clip');prev_btn.clicked.connect(lambda:self.timeline_jump_relative(-1));playback_controls.addWidget(prev_btn)
  next_btn=QPushButton('Next Clip ▶');next_btn.clicked.connect(lambda:self.timeline_jump_relative(1));playback_controls.addWidget(next_btn)
  for caption,delta in [('− 1 frame',-1),('+ 1 frame',1)]:
   btn=QPushButton(caption);btn.setToolTip('Step exactly one video frame')
   btn.clicked.connect(lambda checked=False,d=delta:self.timeline_step(d));playback_controls.addWidget(btn)
  playback_controls.addStretch(1)
  self.timeline_time_label=QLabel('00:00.000 / 00:00.000');playback_controls.addWidget(self.timeline_time_label)
  self.timeline_frame_label=QLabel('Frame —');playback_controls.addWidget(self.timeline_frame_label)
  controls=QHBoxLayout()
  controls.setSpacing(7)
  controls.addWidget(QLabel('CUT EDITING'))
  self.timeline_snap_check=QCheckBox('Frame snap');self.timeline_snap_check.setToolTip('Align moved or added cuts to exact video frame boundaries');self.timeline_snap_check.setChecked(True)
  self.timeline_snap_check.toggled.connect(self.timeline_set_snap);inspector_heading.insertWidget(3,self.timeline_snap_check)
  self.timeline_smart_snap_check=QCheckBox('Smart snap')
  self.timeline_smart_snap_check.setToolTip('Snap within 0.25 seconds of previously detected black, silence or scene transitions. Run automatic detection first.')
  self.timeline_smart_snap_check.toggled.connect(self.timeline_set_smart_snap)
  inspector_heading.insertWidget(4,self.timeline_smart_snap_check)
  for text,fn in [('Add Split',self.timeline_add),('Remove Split',self.timeline_remove),('Undo',self.timeline_undo),('Redo',self.timeline_redo)]:
   btn=QPushButton(text);btn.clicked.connect(fn);controls.addWidget(btn)
  self.motion_preview_button=QPushButton('Preview Split');self.motion_preview_button.setToolTip('Preview playback around the selected split boundary');self.motion_preview_button.clicked.connect(self.timeline_preview_around_split);controls.addWidget(self.motion_preview_button)
  controls.addStretch()
  # Keep playback at the top of the scrollable editor, above the preview,
  # rather than letting the video preview push it below the visible viewport.
  self.timeline_playback_bar=QWidget()
  playback_bar_layout=QVBoxLayout(self.timeline_playback_bar)
  playback_bar_layout.setContentsMargins(4,4,4,4)
  playback_bar_layout.setSpacing(5)
  playback_bar_layout.addLayout(playback_controls)
  playback_bar_layout.addLayout(controls)
  self.timeline_playback_layout=lay
  self.set_timeline_playback_position(self.prefs.get('timeline_playback_position','Top'))
  organizer_toggle=QPushButton('Show Clip Organizer' if not organizer.isVisible() else 'Hide Clip Organizer')
  organizer_toggle.clicked.connect(lambda:self.toggle_timeline_organizer(organizer_toggle))
  tools_heading=QHBoxLayout();tools_heading.addWidget(QLabel('CLIP WORKSPACE'));tools_heading.addStretch();tools_heading.addWidget(organizer_toggle)
  reset_layout=QPushButton('Reset Layout')
  reset_layout.setToolTip('Restore the default preview, inspector and organizer panel sizes')
  reset_layout.clicked.connect(self.reset_timeline_workspace)
  tools_heading.addWidget(reset_layout)
  lay.addLayout(tools_heading)
  self.timeline_bottom_splitter=QSplitter(Qt.Vertical)
  self.timeline_bottom_splitter.setChildrenCollapsible(False)
  self.timeline_bottom_splitter.setHandleWidth(8)
  self.timeline_bottom_splitter.addWidget(self.timeline_tools)
  self.timeline_bottom_splitter.addWidget(organizer)
  sizes=self.prefs.get('timeline_bottom_sizes',[260,250])
  if not isinstance(sizes,list) or len(sizes)!=2 or not all(isinstance(n,int) and n>0 for n in sizes):sizes=[260,250]
  self.timeline_bottom_splitter.setSizes(sizes)
  self.timeline_bottom_splitter.splitterMoved.connect(lambda *_:self.save_ui_preference('timeline_bottom_sizes',self.timeline_bottom_splitter.sizes()))
  lay.addWidget(self.timeline_bottom_splitter,0)
  self.timeline_view.setContextMenuPolicy(Qt.CustomContextMenu)
  self.timeline_view.customContextMenuRequested.connect(self.timeline_context_menu)

  self.split_preview_process=None;self.split_preview_token=0;self.split_preview_cache={};self.split_preview_key=None;self.after_frame_last_live_request=0.
  self.split_preview_debounce=QTimer(self);self.split_preview_debounce.setSingleShot(True)
  self.split_preview_debounce.timeout.connect(self.timeline_launch_debounced_preview)
  self.split_preview_pending=None
  # Retain timeline status text for logic, but remove redundant bottom panel.
  self.timeline_help=QLabel('No video loaded',self);self.timeline_help.hide()
  self.timeline_history=[];self.timeline_future=[]
  # Scrollable timeline page keeps the main window freely resizable.
  # Large preview/video minimum sizes no longer force the top-level window size.
  scroll=QScrollArea()
  scroll.setWidgetResizable(True)
  scroll.setFrameShape(QFrame.NoFrame)
  scroll.setWidget(page)
  self.timeline_scroll=scroll
  scroll.viewport().installEventFilter(self)
  self.stack.addWidget(scroll)
 def timeline_update_view_status(self):
  if not hasattr(self,'timeline_visible_label'):return
  a,b=self.timeline_visible_range()
  self.timeline_visible_label.setText(f'{fmt(a)} – {fmt(b)}')
  self.timeline_visible_label.setToolTip('Current visible timeline time range')
  visible=sum(1 for t in self.cuts if a<=t<=b)
  self.timeline_marker_count.setText(f'{visible} visible / {len(self.cuts)} placed splits')

 def timeline_navigate_marker(self,direction):
  if not self.video or not self.duration or not self.cuts:return
  times=sorted(self.cuts)
  now=self.timeline_player.position()/1000
  if direction>0:
   target=next((t for t in times if t>now+.06),times[-1])
  else:
   target=next((t for t in reversed(times) if t<now-.06),times[0])
  self.timeline_stop_motion_preview()
  self.timeline_player.pause()
  self.timeline_player.setPosition(round(target*1000))
  if self.timeline_zoom_factor>1:
   span=self.duration/self.timeline_zoom_factor
   start=max(0.,min(self.duration-span,target-span*.5))
   self.timeline_pan.setValue(round(1000*start/max(.001,self.duration-span)))
  self.timeline_request_split_preview(target)
  self.timeline_show_inspector_still(target)
  self.timeline_view.update()

 def timeline_visible_range(self):
  duration=max(.001,self.duration)
  span=duration/max(1,self.timeline_zoom_factor)
  start=(duration-span)*self.timeline_pan_fraction
  return start,min(duration,start+span)
 def timeline_wheel_zoom(self,delta,global_point):
  if not self.video or not self.duration or not delta:return False
  # Map from the global cursor position to the actual timeline widget,
  # not to the scroll area's viewport or the window.
  view=self.timeline_view
  local=view.mapFromGlobal(global_point)
  left,width,_=view.geometry_data()
  ratio=max(0.,min(1.,(local.x()-left)/max(1,width)))
  start,end=self.timeline_visible_range()
  anchor=start+ratio*(end-start)
  direction=1 if delta>0 else -1
  target=max(self.timeline_zoom.minimum(),min(self.timeline_zoom.maximum(),self.timeline_zoom.value()+direction))
  if target==self.timeline_zoom.value():return True
  self.timeline_zoom_at(target,anchor,ratio)
  return True
 def eventFilter(self,watched,event):
  # When the timeline is inside a scroll area, its viewport can receive
  # wheel events instead of the timeline itself. Forward those consistently.
  if event.type()==QEvent.Wheel and hasattr(self,'timeline_scroll') and watched is self.timeline_scroll.viewport():
   pos=event.globalPosition().toPoint()
   local=self.timeline_view.mapFromGlobal(pos)
   if self.timeline_view.rect().contains(local) and 29<=local.y()<=self.timeline_view.height():
    if self.timeline_wheel_zoom(event.angleDelta().y(),pos):
     event.accept()
     return True
  if event.type()==QEvent.Resize:
   if hasattr(self,'after_frame_picture') and watched is self.after_frame_picture:
    pix=getattr(self,'timeline_before_original',None)
    if pix is not None and not pix.isNull():
     self.after_frame_picture.setPixmap(pix.scaled(max(1,watched.width()-12),max(1,watched.height()-12),Qt.KeepAspectRatio,Qt.SmoothTransformation))
   elif hasattr(self,'timeline_still') and watched is self.timeline_still:
    pix=getattr(self,'timeline_current_original',None)
    if pix is not None and not pix.isNull():
     self.timeline_still.setPixmap(pix.scaled(max(1,watched.width()-8),max(1,watched.height()-8),Qt.KeepAspectRatio,Qt.SmoothTransformation))
  return super().eventFilter(watched,event)
 def timeline_zoom_at(self,value,anchor_time,screen_fraction):
  # Wheel zoom: explicitly calculate the viewport around the pointer.
  # Updating the slider must not run a second, playhead-centered zoom.
  value=max(self.timeline_zoom.minimum(),min(self.timeline_zoom.maximum(),int(value)))
  duration=max(.001,self.duration)
  new_factor=2**value
  span=duration/new_factor
  screen_fraction=max(0.,min(1.,float(screen_fraction)))
  anchor_time=max(0.,min(duration,float(anchor_time)))
  start=max(0.,min(duration-span,anchor_time-screen_fraction*span))
  self.timeline_zoom.blockSignals(True)
  self.timeline_zoom.setValue(value)
  self.timeline_zoom.blockSignals(False)
  self.timeline_zoom_factor=new_factor
  self.timeline_pan_fraction=start/max(.001,duration-span) if value else 0.
  self.timeline_pan.blockSignals(True)
  self.timeline_pan.setValue(round(self.timeline_pan_fraction*1000))
  self.timeline_pan.setEnabled(value>0)
  self.timeline_pan.blockSignals(False)
  self.timeline_zoom_label.setText(f'{new_factor}×')
  actual_start,actual_end=self.timeline_visible_range()
  self.timeline_zoom_label.setToolTip(f'Visible: {fmt(actual_start)} – {fmt(actual_end)}; cursor anchor: {fmt(anchor_time)}')
  self.timeline_view.update();self.timeline_update_view_status()
  if self.video and self.duration:self.timeline_schedule_refresh()
 def timeline_zoom_changed(self,value):
  old_start,old_end=self.timeline_visible_range()
  # Keep the current red playhead fixed at its relative screen position.
  wheel_anchor=self.timeline_wheel_anchor
  if wheel_anchor is not None:
   anchor,screen_fraction=wheel_anchor
  else:
   anchor=self.timeline_view.scrub_time if self.timeline_view.scrubbing and self.timeline_view.scrub_time is not None else self.timeline_player.position()/1000
   anchor=max(0,min(max(.001,self.duration),anchor))
   old_span=max(.001,old_end-old_start)
   screen_fraction=max(0,min(1,(anchor-old_start)/old_span))
  self.timeline_zoom_factor=2**value
  duration=max(.001,self.duration);span=duration/self.timeline_zoom_factor
  fraction=max(0,min(1,(anchor-screen_fraction*span)/max(.001,duration-span))) if self.timeline_zoom_factor>1 else 0
  self.timeline_pan.blockSignals(True);self.timeline_pan.setValue(round(fraction*1000));self.timeline_pan.setEnabled(value>0);self.timeline_pan.blockSignals(False)
  self.timeline_pan_fraction=fraction;self.timeline_zoom_label.setText(f'{self.timeline_zoom_factor}×')
  self.timeline_view.update();self.timeline_update_view_status();self.timeline_schedule_refresh() if self.video and self.duration else None
 def timeline_pan_changed(self,value):
  self.timeline_pan_fraction=value/1000
  self.timeline_view.update();self.timeline_update_view_status()
  if self.video and self.duration:self.timeline_schedule_refresh()
 def clip_filename(self,index):
  raw=self.clip_names.get(str(index),'').strip()
  if not raw:return f'Commercial_{index+1:03d}.mp4'
  return safe_folder_name(raw.removesuffix('.mp4'))+'.mp4'
 def timeline_save_clip_name(self):
  if not self.video:return
  index=self.timeline_clip_select.currentIndex()
  if index<0:return
  raw=self.timeline_clip_name.text().strip()
  if raw.lower().endswith('.mp4'):raw=raw[:-4]
  if raw:
   clean=safe_folder_name(raw)
   self.clip_names[str(index)]=clean
   if clean!=raw:
    self.timeline_clip_name.setText(clean)
  else:self.clip_names.pop(str(index),None)
  self.save_recovery()
  # Update the current dropdown entry immediately without rebuilding the list
  # or changing the selected clip / playback position.
  t=self.timeline_clip_select.itemData(index)
  name=self.clip_names.get(str(index),'')
  label=f'Clip {index+1} — {fmt(float(t))}'+(f' — {name}' if name else '')
  self.timeline_clip_select.setItemText(index,label)
  self.timeline_refresh_clip_name()
  self.timeline_update_organizer_labels()
 def timeline_suggest_clip_name(self):
  if not self.video:return
  index=self.timeline_clip_select.currentIndex()
  if index<0:return
  self.timeline_clip_name.setText(f'{safe_folder_name(Path(self.video).stem)} - Clip {index+1:03d}')
  self.timeline_save_clip_name()
 def timeline_refresh_clip_name(self):
  if not hasattr(self,'timeline_clip_name'):return
  index=self.timeline_clip_select.currentIndex()
  self.timeline_clip_name.blockSignals(True)
  self.timeline_clip_name.setText(self.clip_names.get(str(index),'') if index>=0 else '')
  self.timeline_clip_name.setEnabled(bool(self.video) and index>=0)
  self.timeline_clip_name.blockSignals(False)
 def timeline_update_clips(self):
  if not hasattr(self,'timeline_clip_select'):return
  previous=self.timeline_clip_select.currentIndex()
  self.timeline_clip_select.blockSignals(True);self.timeline_clip_select.clear()
  if self.video and self.duration:
   bounds=[0.0]+list(self.cuts)
   for i,t in enumerate(bounds):
    name=self.clip_names.get(str(i),'')
    self.timeline_clip_select.addItem(f'Clip {i+1} — {fmt(t)}'+(f' — {name}' if name else ''),t)
   now=self.timeline_player.position()/1000
   self.timeline_clip_select.setCurrentIndex(max(0,min(bisect.bisect_right(self.cuts,now),len(bounds)-1)))
  self.timeline_clip_select.blockSignals(False)
  self.timeline_refresh_clip_name()
  self.timeline_update_organizer()
 def normalized_clip_order(self):
  count=len(self.segments()) if self.video and self.duration else 0
  order=[]
  for x in getattr(self,'clip_order',[]):
   if isinstance(x,int) and 0<=x<count and x not in order:order.append(x)
  order.extend(i for i in range(count) if i not in order)
  return order
 def organizer_relayout(self):
  if not hasattr(self,'clip_organizer_items'):return
  for pos,index in enumerate(self.normalized_clip_order()):
   if index<len(self.clip_organizer_items):
    card=self.clip_organizer_items[index][0]
    self.clip_organizer_layout.removeWidget(card)
    self.clip_organizer_layout.insertWidget(pos,card)
 def reorder_clip(self,source,target,after=False):
  order=self.normalized_clip_order()
  if source==target or source not in order or target not in order:return
  order.remove(source)
  order.insert(order.index(target)+(1 if after else 0),source)
  self.clip_order=order
  self.organizer_relayout();self.timeline_update_organizer_labels();self.save_recovery()
  self.status.setText('Export order updated; original video cuts are unchanged')
  if self.stack.currentIndex()==3:self.populate_gallery()
 def timeline_update_organizer_labels(self):
  if not hasattr(self,'clip_organizer_items'):return
  for i,(button,picture,caption) in enumerate(self.clip_organizer_items):
   start=([0.]+list(self.cuts))[i] if i<=len(self.cuts) else 0.
   end=([0.]+list(self.cuts)+[self.duration])[i+1] if i<=len(self.cuts) else start
   name=self.clip_names.get(str(i),'').strip() or f'Commercial {i+1:03d}'
   order=self.normalized_clip_order()
   position=order.index(i)+1
   caption.setText(f'Export #{position} • Clip {i+1}\n{name}\n{fmt(max(0,end-start))}')
   button.setStyleSheet('border:3px solid #f5bc5d;border-radius:6px;' if i in self.organizer_selected else ('border:2px solid #52c9bd;border-radius:6px;' if i==self.timeline_clip_select.currentIndex() else 'border:1px solid #405168;border-radius:6px;'))
  if hasattr(self,'organizer_selection_label'):self.organizer_selection_label.setText(f'{len(self.organizer_selected)} clips selected • {len(self.batch_excluded)} excluded from export')
 def timeline_organizer_select(self,index):
  if index>=self.timeline_clip_select.count():return
  modifiers=QApplication.keyboardModifiers()
  order=self.normalized_clip_order()
  if modifiers & Qt.ShiftModifier and self.organizer_anchor in order:
   a,b=order.index(self.organizer_anchor),order.index(index)
   selection=set(order[min(a,b):max(a,b)+1])
   if modifiers & Qt.ControlModifier:self.organizer_selected.update(selection)
   else:self.organizer_selected=selection
  elif modifiers & Qt.ControlModifier:
   if index in self.organizer_selected:self.organizer_selected.remove(index)
   else:self.organizer_selected.add(index)
   self.organizer_anchor=index
  else:
   self.organizer_selected={index};self.organizer_anchor=index
  self.timeline_clip_select.setCurrentIndex(index)
  self.timeline_jump_to_selected()
  self.timeline_update_organizer_labels()
 def organizer_clear_selection(self):
  self.organizer_selected.clear();self.organizer_anchor=None
  self.timeline_update_organizer_labels()
 def organizer_batch_prefix(self):
  if not self.video or not self.organizer_selected:return
  prefix=safe_folder_name(self.batch_prefix.text().strip())
  if not prefix:return
  for i in sorted(self.organizer_selected):
   old=self.clip_names.get(str(i),'').strip() or f'Commercial {i+1:03d}'
   if not old.startswith(prefix+' - '):self.clip_names[str(i)]=safe_folder_name(prefix+' - '+old)
  self.save_recovery();self.timeline_update_clips()
  if self.stack.currentIndex()==3:self.populate_gallery()
  self.status.setText(f'Applied prefix to {len(self.organizer_selected)} clips')
 def organizer_batch_include(self,include):
  if not self.organizer_selected:return
  if include:self.batch_excluded.difference_update(self.organizer_selected)
  else:self.batch_excluded.update(self.organizer_selected)
  self.timeline_update_organizer_labels()
  if self.stack.currentIndex()==3:self.populate_gallery()
  self.status.setText(f'{len(self.organizer_selected)} selected clips marked '+('included' if include else 'excluded')+' for export')
 def timeline_stop_organizer(self):
  self.clip_organizer_token+=1
  proc=self.clip_organizer_process;self.clip_organizer_process=None
  if proc is not None:
   proc.blockSignals(True)
   if proc.state()!=QProcess.NotRunning:proc.kill()
   proc.deleteLater()
 def timeline_update_organizer(self):
  if not hasattr(self,'clip_organizer_layout'):return
  bounds=[0.]+list(self.cuts)+[self.duration] if self.video and self.duration else []
  signature=(self.video,tuple(round(x,3) for x in bounds))
  if signature==self.clip_organizer_signature:
   self.timeline_update_organizer_labels();return
  self.timeline_stop_organizer()
  self.clip_organizer_signature=signature
  self.organizer_selected.intersection_update(range(max(0,len(bounds)-1)))
  self.batch_excluded.intersection_update(range(max(0,len(bounds)-1)))
  self.clip_organizer_items=[]
  while self.clip_organizer_layout.count():
   item=self.clip_organizer_layout.takeAt(0)
   if item.widget():item.widget().deleteLater()
  self.clip_organizer_queue=[]
  for i in range(max(0,len(bounds)-1)):
   start,end=bounds[i:i+2]
   card=OrganizerCard(self,i);card.setFixedWidth(170);card.setMinimumHeight(143)
   card.setToolTip(f'Jump to clip {i+1} at {fmt(start)}')
   card.clicked.connect(lambda checked=False,idx=i:self.timeline_organizer_select(idx))
   vertical=QVBoxLayout(card);vertical.setContentsMargins(5,5,5,5)
   picture=QLabel('Loading thumbnail…');picture.setAlignment(Qt.AlignCenter)
   picture.setFixedSize(156,88);picture.setStyleSheet('background:#1b2836;color:#b7c6d4;')
   caption=QLabel();caption.setWordWrap(True);caption.setAlignment(Qt.AlignCenter)
   caption.setMaximumHeight(38)
   vertical.addWidget(picture);vertical.addWidget(caption)
   self.clip_organizer_layout.addWidget(card)
   self.clip_organizer_items.append((card,picture,caption))
   cache_key=(self.video,round(start,3),round(end,3))
   if cache_key in self.clip_organizer_cache:
    picture.setPixmap(self.clip_organizer_cache[cache_key])
   else:self.clip_organizer_queue.append((i,cache_key,min(end-.001,start+max(.05,min(1.,(end-start)*.25)))))
  self.clip_organizer_layout.addStretch()
  self.organizer_relayout()
  self.timeline_update_organizer_labels()
  self.timeline_next_organizer_thumbnail(self.clip_organizer_token)
 def timeline_next_organizer_thumbnail(self,token):
  if token!=self.clip_organizer_token or not self.clip_organizer_queue:return
  ffmpeg=tool('ffmpeg')
  if not ffmpeg:return
  idx,key,at=self.clip_organizer_queue.pop(0)
  proc=QProcess(self);self.clip_organizer_process=proc
  proc.setProgram(ffmpeg)
  proc.setArguments(['-hide_banner','-loglevel','error','-nostdin','-ss',f'{max(0.,at):.3f}','-i',self.video,'-frames:v','1','-vf','scale=156:88:force_original_aspect_ratio=increase,crop=156:88','-f','image2pipe','-vcodec','mjpeg','-'])
  proc.finished.connect(lambda code,status,tk=token,i=idx,k=key,pr=proc:self.timeline_organizer_thumbnail_finished(tk,i,k,pr,code))
  proc.errorOccurred.connect(lambda err,tk=token,i=idx,k=key,pr=proc:self.timeline_organizer_thumbnail_error(tk,i,k,pr))
  proc.start()
 def timeline_organizer_thumbnail_error(self,token,index,key,proc):
  if token==self.clip_organizer_token and proc is self.clip_organizer_process and proc.state()==QProcess.NotRunning:
   self.timeline_organizer_thumbnail_finished(token,index,key,proc,-1)
 def timeline_organizer_thumbnail_finished(self,token,index,key,proc,code):
  if token!=self.clip_organizer_token or proc is not self.clip_organizer_process:return
  if code==0:
   pix=QPixmap();pix.loadFromData(bytes(proc.readAllStandardOutput()))
   if not pix.isNull() and index<len(self.clip_organizer_items):
    self.clip_organizer_cache[key]=pix
    self.clip_organizer_items[index][1].setPixmap(pix)
  self.clip_organizer_process=None;proc.deleteLater()
  QTimer.singleShot(0,lambda tk=token:self.timeline_next_organizer_thumbnail(tk))
 def timeline_clip_changed(self,index):
  self.timeline_refresh_clip_name()
  self.timeline_update_organizer_labels()
  if index>=0 and self.video and self.duration:
   self.timeline_jump_to_selected()

 def timeline_jump_to_selected(self):
  self.timeline_stop_motion_preview()
  if not self.video or self.timeline_clip_select.currentIndex()<0:return
  t=float(self.timeline_clip_select.currentData())
  self.timeline_player.pause();self.timeline_player.setPosition(round(t*1000))
  if self.timeline_zoom_factor>1:
   span=self.duration/self.timeline_zoom_factor
   fraction=max(0,min(1,(t-span*.15)/max(.001,self.duration-span)))
   self.timeline_pan.setValue(round(fraction*1000))
  self.timeline_view.update()
 def timeline_jump_relative(self,direction):
  if not self.video or not self.duration:return
  starts=[0.0]+list(self.cuts);now=self.timeline_player.position()/1000
  if direction>0:idx=next((i for i,t in enumerate(starts) if t>now+.08),len(starts)-1)
  else:idx=next((i for i in range(len(starts)-1,-1,-1) if starts[i]<now-.08),0)
  self.timeline_clip_select.setCurrentIndex(idx);self.timeline_jump_to_selected()
 def timeline_refresh(self):
  if not hasattr(self,'timeline_player'):return
  self.timeline_update_view_status()
  if self.timeline_media_path!=self.video:self.timeline_stop_motion_preview()
  if self.video and self.timeline_media_path!=self.video:
   self.timeline_pending_inspector_seek=None
   self.timeline_player.stop();self.timeline_player.setSource(QUrl.fromLocalFile(self.video));self.timeline_media_path=self.video
   self.timeline_history.clear();self.timeline_future.clear();self.timeline_view.selected=None;self.split_preview_cache.clear();self.timeline_still_cache.clear()
  if self.video and self.duration and (self.timeline_thumb_video!=self.video or abs(self.timeline_thumb_duration-self.duration)>.01):
   self.timeline_start_thumbnails()
  if not self.video and self.timeline_media_path:
   self.timeline_player.stop();self.timeline_player.setSource(QUrl());self.timeline_media_path=None;self.timeline_clear_current_preview();self.timeline_history.clear();self.timeline_future.clear();self.timeline_view.selected=None
   self.timeline_stop_thumbnails()
  self.timeline_view.update();self.timeline_update_clips();self.timeline_selection_changed()
 def timeline_schedule_refresh(self):
  # Coalesce rapid pan/zoom changes; avoid spawning FFmpeg per slider tick.
  self.timeline_refresh_timer.start()
 def timeline_stop_thumbnails(self):
  self.timeline_refresh_timer.stop()
  self.timeline_thumb_token+=1
  self.timeline_wave_token+=1
  wave=self.timeline_wave_process;self.timeline_wave_process=None;self.timeline_waveform=[];self.timeline_wave_buffer=bytearray()
  if wave is not None:
   wave.blockSignals(True)
   if wave.state()!=QProcess.NotRunning:wave.kill()
   wave.deleteLater()
  proc=self.timeline_thumb_process
  self.timeline_thumb_process=None
  if proc is not None:
   try:
    proc.blockSignals(True)
    if proc.state()!=QProcess.NotRunning:proc.kill()
    proc.deleteLater()
   except RuntimeError:pass
  self.timeline_thumb_video=None;self.timeline_thumb_duration=0;self.timeline_thumb_range=None;self.timeline_thumbs=[]
  self.timeline_view.update()
 def timeline_start_thumbnails(self):
  if not self.video or not self.duration:
   self.timeline_stop_thumbnails()
   return
  requested=self.timeline_visible_range()
  # Skip redundant redraw jobs when the visible region has not changed.
  # Previously even an unchanged pan/zoom refresh killed and restarted
  # FFmpeg waveform and thumbnail extraction.
  if (self.timeline_thumb_video==self.video
      and abs(self.timeline_thumb_duration-self.duration)<.01
      and self.timeline_thumb_range is not None
      and abs(self.timeline_thumb_range[0]-requested[0])<.01
      and abs(self.timeline_thumb_range[1]-requested[1])<.01):
   self.timeline_view.update()
   return
  self.timeline_stop_thumbnails()
  self.timeline_thumb_video=self.video;self.timeline_thumb_duration=self.duration;self.timeline_thumb_range=requested
  # One process at a time keeps seeking responsive, even on long recordings.
  self.timeline_start_waveform()
  cache_key=(self.video,round(self.timeline_thumb_range[0],2),round(self.timeline_thumb_range[1],2))
  if cache_key in self.timeline_thumb_cache:
   self.timeline_thumbs=list(self.timeline_thumb_cache[cache_key]);self.timeline_view.update();return
  self.timeline_thumbs=[None]*12;self.timeline_thumb_index=0
  self.timeline_view.update()
  self.timeline_next_thumbnail(self.timeline_thumb_token)
 def timeline_start_waveform(self):
  self.timeline_wave_token+=1
  old=self.timeline_wave_process;self.timeline_wave_process=None;self.timeline_waveform=[]
  if old is not None:
   old.blockSignals(True)
   if old.state()!=QProcess.NotRunning:old.kill()
   old.deleteLater()
  if not self.video or not self.duration:return
  start,end=self.timeline_visible_range()
  key=(self.video,round(start,2),round(end,2))
  self.timeline_wave_key=key
  if key in self.timeline_wave_cache:
   self.timeline_waveform=list(self.timeline_wave_cache[key]);self.timeline_view.update();return
  ffmpeg=tool('ffmpeg')
  if not ffmpeg:return
  start,end=self.timeline_visible_range()
  # 8000 Hz mono PCM, capped at ~500k samples to keep memory bounded.
  rate=max(1000,min(8000,int(500000/max(.1,end-start))))
  proc=QProcess(self);self.timeline_wave_process=proc;self.timeline_wave_buffer=bytearray()
  token=self.timeline_wave_token
  proc.setProgram(ffmpeg)
  proc.setArguments(['-hide_banner','-loglevel','error','-nostdin','-ss',f'{start:.3f}','-i',self.video,'-t',f'{end-start:.3f}','-vn','-ac','1','-ar',str(rate),'-f','s16le','-acodec','pcm_s16le','-'])
  proc.readyReadStandardOutput.connect(lambda tk=token,pr=proc:self.timeline_wave_read(tk,pr))
  proc.finished.connect(lambda code,status,tk=token,pr=proc:self.timeline_wave_finished(tk,pr,code))
  proc.start()
 def timeline_wave_read(self,token,proc):
  if token!=self.timeline_wave_token or proc is not self.timeline_wave_process:return
  self.timeline_wave_buffer.extend(bytes(proc.readAllStandardOutput()))
 def timeline_wave_finished(self,token,proc,code):
  if token!=self.timeline_wave_token or proc is not self.timeline_wave_process:return
  if code==0:
   import array
   self.timeline_wave_read(token,proc)
   raw=bytes(self.timeline_wave_buffer)
   samples=array.array('h');samples.frombytes(raw[:len(raw)//2*2])
   if sys.byteorder!='little':samples.byteswap()
   bins=1000
   peaks=[]
   # Scan the PCM array once without allocating 1000 intermediate slices.
   sample_count=len(samples)
   for i in range(bins):
    a=i*sample_count//bins;b=(i+1)*sample_count//bins
    peak=0
    for j in range(a,b):
     value=abs(samples[j])
     if value>peak:peak=value
    peaks.append(peak/32768)
   self.timeline_waveform=peaks
   if self.timeline_wave_key is not None:
    self.timeline_wave_cache[self.timeline_wave_key]=list(peaks)
    if len(self.timeline_wave_cache)>8:self.timeline_wave_cache.pop(next(iter(self.timeline_wave_cache)))
  self.timeline_wave_process=None;self.timeline_wave_buffer=bytearray();proc.deleteLater();self.timeline_view.update()
 def timeline_next_thumbnail(self,token):
  if token!=self.timeline_thumb_token or not self.video:return
  index=self.timeline_thumb_index
  if index>=len(self.timeline_thumbs):
   key=(self.video,round(self.timeline_thumb_range[0],2),round(self.timeline_thumb_range[1],2))
   if all(p is not None for p in self.timeline_thumbs):
    self.timeline_thumb_cache[key]=tuple(self.timeline_thumbs)
    if len(self.timeline_thumb_cache)>6:self.timeline_thumb_cache.pop(next(iter(self.timeline_thumb_cache)))
   return
  ffmpeg=tool('ffmpeg')
  if not ffmpeg:return
  start,end=self.timeline_thumb_range;t=start+(end-start)*(index+.5)/len(self.timeline_thumbs)
  proc=QProcess(self);self.timeline_thumb_process=proc
  proc.setProgram(ffmpeg)
  proc.setArguments(['-hide_banner','-loglevel','error','-nostdin','-ss',f'{t:.3f}','-i',self.video,'-frames:v','1','-vf','scale=180:90:force_original_aspect_ratio=decrease,pad=180:90:(ow-iw)/2:(oh-ih)/2','-f','image2pipe','-vcodec','mjpeg','-'])
  proc.finished.connect(lambda code,status,tk=token,idx=index,pr=proc:self.timeline_thumbnail_finished(tk,idx,pr,code))
  proc.errorOccurred.connect(lambda error,tk=token,idx=index,pr=proc:self.timeline_thumbnail_error(tk,idx,pr))
  proc.start()
 def timeline_thumbnail_error(self,token,index,proc):
  if token!=self.timeline_thumb_token or proc is not self.timeline_thumb_process:return
  if proc.state()==QProcess.NotRunning:self.timeline_thumbnail_finished(token,index,proc,-1)
 def timeline_thumbnail_finished(self,token,index,proc,code):
  if token!=self.timeline_thumb_token or proc is not self.timeline_thumb_process:return
  if code==0:
   pix=QPixmap();pix.loadFromData(bytes(proc.readAllStandardOutput()))
   if not pix.isNull():self.timeline_thumbs[index]=pix
  self.timeline_thumb_process=None
  proc.deleteLater();self.timeline_thumb_index=index+1
  self.timeline_view.update()
  QTimer.singleShot(0,lambda tk=token:self.timeline_next_thumbnail(tk))
 def timeline_smart_snap_time(self,t,exclude=None):
  if not self.timeline_smart_snap_enabled:return t
  # Use detected evidence, not existing accepted cut positions. Manual
  # cuts must never pull other cuts into themselves.
  targets=[]
  for c in self.candidates:
   if c.get('source') in ('Hybrid detection','Scene scan') or c.get('confidence'):
    if not c.get('rejected'):
     targets.append(float(c['time']))
  for start,end,length in self.auto_black_intervals:
   if length>=.08:targets.append((start+end)/2)
  for start,end,length in self.auto_silence_intervals:
   if length>=.15:targets.extend((start,end))
  targets.extend(self.auto_visual_times)
  if exclude is not None:targets=[v for v in targets if abs(v-exclude)>.002]
  near=min(targets,key=lambda v:abs(v-t),default=None)
  if near is not None and abs(near-t)<=.25:return near
  return t
 def timeline_set_smart_snap(self,enabled):
  self.timeline_smart_snap_enabled=enabled
  self.status.setText('Smart snapping enabled (uses previous detection results)' if enabled else 'Smart snapping disabled')
 def timeline_snap_time(self,t):
  t=max(.001,min(max(.001,self.duration-.001),float(t)))
  if self.timeline_snap_enabled and self.fps>0:
   t=round(t*self.fps)/self.fps
  return round(max(.001,min(max(.001,self.duration-.001),t)),6)
 def timeline_set_snap(self,enabled):
  self.timeline_snap_enabled=enabled
  self.status.setText('Frame snapping enabled' if enabled else 'Frame snapping disabled')
 def timeline_wave_mode_changed(self,index):
  self.save_ui_preference('timeline_wave_mode',index)
  self.timeline_view.setFixedHeight(330 if index==1 else 190)
  self.timeline_view.update()
 def timeline_refresh_paused_still(self):
  if (self.video and not self.timeline_player.isPlaying()
      and self.timeline_video_stack.currentIndex()==1):
   self.timeline_show_inspector_still(self.timeline_player.position()/1000.)

 def timeline_position_changed(self,pos):
  if self.duration:self.timeline_time_label.setText(f'{fmt(pos/1000)} / {fmt(self.duration)}')
  self.timeline_frame_label.setText(f'Frame {round(pos*self.fps/1000):,}  ·  {self.fps:.3f} fps' if self.video else 'Frame —')
  self.timeline_view.update()
  # The inspector uses a still image while paused. Keep it synchronized with
  # keyboard stepping, navigation buttons and playhead scrubbing, not just Play.
  if (self.video and self.timeline_video_stack.currentIndex()==1
      and not self.timeline_player.isPlaying()):
   self.timeline_paused_still_timer.start()
  # Update Before Frame during playback as well as paused seeking.
  # Limit FFmpeg requests to avoid continually killing an in-flight decode.
  if self.video and hasattr(self,'after_frame_picture') and not self.timeline_view.scrubbing:
   now=time.monotonic()
   playing=self.timeline_player.isPlaying()
   interval=1.0 if playing else 0.30
   if now-getattr(self,'after_frame_last_live_request',0.)>=interval:
    if self.split_preview_process is None or self.split_preview_process.state()==QProcess.NotRunning:
     self.after_frame_last_live_request=now
     self.timeline_request_split_preview(cut_time=min(self.duration,max(0.,pos/1000)),live=True)
 def timeline_stop_motion_preview(self,pause=False):
  active=self.timeline_motion_preview_end is not None
  self.timeline_motion_preview_end=None
  self.timeline_motion_preview_started=False
  self.timeline_motion_preview_timer.stop()
  if hasattr(self,'motion_preview_button'):
   self.motion_preview_button.setText('▶ Preview Around Split')
  if active and pause:self.timeline_player.pause()
 def timeline_preview_around_split(self):
  if not self.video or not self.duration:return
  if self.timeline_motion_preview_end is not None:
   self.timeline_stop_motion_preview(pause=True)
   return
  idx=self.timeline_view.selected
  if idx is None or idx<0 or idx>=len(self.cuts):
   self.status.setText('Select a yellow split marker to preview its transition')
   return
  cut=self.cuts[idx]
  start=max(0.,cut-2.)
  end=min(self.duration,cut+2.)
  if end<=start:return
  self.timeline_motion_preview_end=end*1000
  self.timeline_motion_preview_started=False
  self.motion_preview_button.setText('■ Stop Split Preview')
  self.timeline_player.pause()
  self.timeline_player.setPosition(round(start*1000))
  self.timeline_player.play()
  self.timeline_motion_preview_timer.start()
  self.status.setText(f'Previewing split {idx+1}: {fmt(start)} – {fmt(end)}')
 def timeline_check_motion_preview(self):
  if self.timeline_motion_preview_end is None:return
  pos=self.timeline_player.position()
  if self.timeline_player.isPlaying():self.timeline_motion_preview_started=True
  if self.timeline_motion_preview_started and (pos>=self.timeline_motion_preview_end-20 or not self.timeline_player.isPlaying()):
   self.timeline_stop_motion_preview(pause=True)
 def timeline_toggle(self):
  self.timeline_stop_motion_preview()
  if not self.video:return
  if self.timeline_player.isPlaying():self.timeline_player.pause()
  else:
   self.timeline_paused_still_timer.stop()
   self.timeline_video_stack.setCurrentIndex(0)
   self.timeline_player.play()
 def timeline_step(self,frames):
  self.timeline_stop_motion_preview()
  if not self.video:return
  self.timeline_player.pause()
  # Compute the target from a frame index, rather than repeatedly adding rounded milliseconds.
  current=round(self.timeline_player.position()*self.fps/1000)
  target=max(0,min(round(self.duration*self.fps),current+frames))
  target_seconds=target/max(1,self.fps)
  self.timeline_player.setPosition(round(target_seconds*1000))
  if self.timeline_video_stack.currentIndex()==1:
   self.timeline_paused_still_timer.start()
  # A paused Qt media backend may not emit positionChanged for every frame
  # step (especially for sub-40ms seeks). Update Before Frame explicitly.
  # Suppress the redundant positionChanged preview request briefly so it
  # cannot cancel the FFmpeg extraction we just started.
  self.after_frame_last_live_request=time.monotonic()
  self.timeline_request_split_preview(cut_time=target_seconds,live=True)
 def timeline_cancel_split_preview(self):
  self.split_preview_debounce.stop()
  self.split_preview_pending=None
  self.split_preview_token+=1
  proc=self.split_preview_process;self.split_preview_process=None
  if proc is not None:
   proc.blockSignals(True)
   if proc.state()!=QProcess.NotRunning:proc.kill()
   proc.deleteLater()
 def timeline_request_split_preview(self,cut_time=None,live=False):
  if not hasattr(self,'after_frame_picture'):return
  idx=self.timeline_view.selected
  # A pending frame extraction for this exact position need not restart.
  if live and self.split_preview_key is not None and abs(self.split_preview_key[1]-round(float(cut_time),6))<0.45/max(1.,self.fps):
   return
  self.timeline_cancel_split_preview()
  if not self.video or (cut_time is None and (idx is None or idx>=len(self.cuts))):
   self.split_preview_title.setText('Select a yellow split marker to inspect its boundary')
   self.after_frame_picture.clear();self.after_frame_picture.setText('Select a split marker')
   self.split_preview_key=None
   return
  cut=float(cut_time) if cut_time is not None else self.cuts[idx];fps=max(1.,self.fps)
  # A nominal frame period; best suited to constant-frame-rate recordings.
  before=max(0.,cut-1.0/fps)
  key=(self.video,round(cut,6),round(fps,4))
  self.split_preview_key=key
  self.after_frame_live_key=key if live else None
  self.split_preview_title.setText((f'Before playhead at {fmt(cut)}' if live else f'Review cut at {fmt(cut)}' if cut_time is not None else f'Split {idx+1} at {fmt(cut)}')+f'  ·  frame interval ≈ {1000/fps:.1f} ms')
  if key in self.split_preview_cache:
   self.timeline_display_split_frame(self.after_frame_picture,self.split_preview_cache[key])
   return
  # Keep the last frame visible during rapid stepping; decode only after
  # navigation settles instead of launching FFmpeg for every key press.
  self.split_preview_pending=(self.split_preview_token,before,key)
  self.split_preview_debounce.start(45 if live else 0)
 def timeline_launch_debounced_preview(self):
  pending=self.split_preview_pending
  self.split_preview_pending=None
  if pending is not None:self.timeline_next_split_frame(*pending)
 def timeline_display_split_frame(self,label,pix):
  self.timeline_before_original=pix if pix is not None and not pix.isNull() else None
  if self.timeline_before_original is None:label.clear();label.setText('Frame unavailable')
  else:
   label.setText('');label.setPixmap(pix.scaled(max(1,label.width()-12),max(1,label.height()-12),Qt.KeepAspectRatio,Qt.SmoothTransformation))
 def timeline_next_split_frame(self,token,before,key):
  if token!=self.split_preview_token or key!=self.split_preview_key:return
  ffmpeg=tool('ffmpeg')
  if not ffmpeg:
   self.after_frame_picture.setText('FFmpeg not found');return
  proc=QProcess(self);self.split_preview_process=proc
  proc.setProgram(ffmpeg)
  proc.setArguments(['-hide_banner','-loglevel','error','-nostdin','-ss',f'{before:.6f}','-i',self.video,'-frames:v','1','-vf','scale=480:270:force_original_aspect_ratio=decrease','-f','image2pipe','-vcodec','png','-'])
  proc.finished.connect(lambda code,status,tk=token,pr=proc,k=key:self.timeline_split_frame_finished(tk,pr,code,k))
  proc.start()
 def timeline_split_frame_finished(self,token,proc,code,key):
  if token!=self.split_preview_token or proc is not self.split_preview_process:return
  pix=QPixmap()
  if code==0:pix.loadFromData(bytes(proc.readAllStandardOutput()))
  result=pix if not pix.isNull() else None
  if result is not None:self.split_preview_cache[key]=result
  if len(self.split_preview_cache)>90:self.split_preview_cache.pop(next(iter(self.split_preview_cache)))
  self.timeline_display_split_frame(self.after_frame_picture,result)
  self.split_preview_process=None;proc.deleteLater()
 def timeline_selection_changed(self):
  idx=self.timeline_view.selected
  if idx is not None:self.timeline_request_split_preview()
  self.timeline_help.setText(f'{len(self.cuts)+1} clips · {len(self.cuts)} splits'+(f' · selected split {idx+1} at {fmt(self.cuts[idx])}' if idx is not None and idx<len(self.cuts) else ' · select a split marker to move or remove'))
 def timeline_snapshot(self):
  self.timeline_history.append([dict(c) for c in self.candidates]);self.timeline_history=self.timeline_history[-60:];self.timeline_future.clear()
 def timeline_commit(self,focus=None):
  self.candidates.sort(key=lambda c:c['time']);self.sync_candidates(focus=focus,queue='scanned');self.save_recovery();self.timeline_view.update();self.timeline_update_clips();self.timeline_selection_changed()
  if self.stack.currentIndex()==3:self.populate_gallery()
 def timeline_add(self):
  if not self.video or self.busy:return
  t=self.timeline_snap_time(self.timeline_smart_snap_time(self.timeline_player.position()/1000))
  if not .001<t<self.duration-.001:return
  if any(abs(t-v)<.05 for v in self.cuts):self.status.setText('A split already exists near this time');return
  self.timeline_snapshot();self.candidates.append({'time':t,'keep':True,'rejected':False,'source':'Timeline manual','confidence':'manual','reason':'Added manually in Timeline Editor'})
  self.timeline_commit();self.inspector_refresh(focus=next((i for i,c in enumerate(self.candidates) if abs(float(c['time'])-t)<.002 and str(c.get('confidence','')).lower()=='manual'),None));self.timeline_view.selected=min(range(len(self.cuts)),key=lambda i:abs(self.cuts[i]-t));self.timeline_selection_changed()
 def timeline_remove(self):
  idx=self.timeline_view.selected
  if not self.video or self.busy or idx is None or idx>=len(self.cuts):return
  t=self.cuts[idx];self.timeline_snapshot()
  for c in self.candidates:
   if c.get('keep') and abs(c['time']-t)<.002:c['keep']=False;c['rejected']=True;c.pop('suggested',None)
  self.timeline_view.selected=None;self.timeline_commit()
 def timeline_move_cut(self,idx,t):
  if not self.video or self.busy or idx<0 or idx>=len(self.cuts):return
  old=self.cuts[idx]
  t=self.timeline_snap_time(self.timeline_smart_snap_time(t,exclude=old))
  if not .001<t<self.duration-.001:
   self.status.setText('Split must remain inside the recording');return
  if abs(t-old)<.001:return
  if any(abs(t-other)<.05 for j,other in enumerate(self.cuts) if j!=idx):self.status.setText('Split markers cannot overlap');return
  self.timeline_snapshot()
  for c in self.candidates:
   if c.get('keep') and abs(c['time']-old)<.002:c['time']=t;break
  self.timeline_commit();self.timeline_view.selected=min(range(len(self.cuts)),key=lambda i:abs(self.cuts[i]-t));self.timeline_selection_changed()
 def timeline_undo(self):
  if not self.video or not self.timeline_history or self.busy:return
  self.timeline_future.append([dict(c) for c in self.candidates]);self.candidates=self.timeline_history.pop();self.timeline_view.selected=None;self.timeline_commit();self.status.setText('Undid cut edit — Review, Timeline and Export boundaries synchronized')
 def timeline_redo(self):
  if not self.video or not self.timeline_future or self.busy:return
  self.timeline_history.append([dict(c) for c in self.candidates]);self.candidates=self.timeline_future.pop();self.timeline_view.selected=None;self.timeline_commit();self.status.setText('Redid cut edit — Review, Timeline and Export boundaries synchronized')
 def save_ui_preference(self,key,value):
  self.prefs[key]=value
  try:self.save_preferences(self.prefs)
  except OSError:pass
 def organizer_card_menu(self,index,position):
  menu=QMenu(self)
  jump=menu.addAction('Jump to clip start')
  include=menu.addAction('Include in export')
  exclude=menu.addAction('Exclude from export')
  menu.addSeparator()
  select=menu.addAction('Select clip')
  chosen=menu.exec(position)
  if chosen==jump:self.timeline_organizer_select(index)
  elif chosen in (include,exclude):
   old=set(self.organizer_selected)
   self.organizer_selected={index}
   self.organizer_batch_include(chosen==include)
   self.organizer_selected=old
   self.timeline_update_organizer_labels()
  elif chosen==select:self.timeline_organizer_select(index)
 def timeline_context_menu(self,position):
  menu=QMenu(self)
  add=menu.addAction('Add split at playhead')
  remove=menu.addAction('Remove selected split')
  menu.addSeparator()
  undo=menu.addAction('Undo')
  redo=menu.addAction('Redo')
  chosen=menu.exec(self.timeline_view.mapToGlobal(position))
  if chosen==add:self.timeline_add()
  elif chosen==remove:self.timeline_remove()
  elif chosen==undo:self.timeline_undo()
  elif chosen==redo:self.timeline_redo()
 def reset_timeline_workspace(self):
  self.timeline_preview_splitter.setSizes([500,500,270])
  self.timeline_bottom_splitter.setSizes([260,250])
  self.save_ui_preference('cut_inspector_widths',[500,500,270])
  self.save_ui_preference('timeline_bottom_sizes',[260,250])
  self.status.setText('Timeline workspace sizes restored to defaults')
 def toggle_timeline_organizer(self,button):
  visible=not self.timeline_organizer_group.isVisible()
  self.timeline_organizer_group.setVisible(visible)
  button.setText('Hide Clip Organizer' if visible else 'Show Clip Organizer')
  self.save_ui_preference('timeline_organizer_visible',visible)
 def make_export(self):
  page=QWidget();lay=QVBoxLayout(page);lay.setSpacing(12)
  title=QLabel('Export');title.setObjectName('heading');lay.addWidget(title)
  self.export_desc=QLabel('Select clips, preview them, and export or queue your selections.');self.export_desc.setObjectName('muted');lay.addWidget(self.export_desc)
  # Keep clip selection and playback visible together; the splitter is user-resizable.
  self.export_workspace=QSplitter(Qt.Horizontal)
  clips_page=QWidget();clips_layout=QVBoxLayout(clips_page);clips_layout.setContentsMargins(2,2,2,2)
  gallery_heading=QHBoxLayout()
  gallery_heading.addWidget(QLabel('CLIP GALLERY  •  Select and organize'))
  gallery_heading.addStretch(1)
  gallery_heading.addWidget(QLabel('View:'))
  self.export_view_mode=QComboBox()
  self.export_view_mode.addItems(['Gallery','Details'])
  self.export_view_mode.setToolTip('Switch between clip cards and a Windows Explorer-style details list')
  self.export_view_mode.setCurrentText(self.prefs.get('export_gallery_view','Gallery'))
  self.export_view_mode.currentTextChanged.connect(self.export_change_view)
  gallery_heading.addWidget(self.export_view_mode)

  self.export_previous_clip=QPushButton('◀ Previous')
  self.export_previous_clip.setToolTip('Select the previous clip in export order')
  self.export_previous_clip.clicked.connect(lambda:self.export_navigate(-1))
  gallery_heading.addWidget(self.export_previous_clip)
  self.export_next_clip=QPushButton('Next ▶')
  self.export_next_clip.setToolTip('Select the next clip in export order')
  self.export_next_clip.clicked.connect(lambda:self.export_navigate(1))
  gallery_heading.addWidget(self.export_next_clip)
  clips_layout.addLayout(gallery_heading)
  self.export_selection_info=QLabel('Select a clip to preview. Check Include in export for each clip.')
  self.export_selection_info.setObjectName('muted')
  clips_layout.addWidget(self.export_selection_info)
  scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setObjectName('scroll');self.gallery=QWidget();self.gallery_layout=QGridLayout(self.gallery);self.gallery_layout.setAlignment(Qt.AlignTop);self.gallery_layout.setSpacing(9);scroll.setWidget(self.gallery);self.export_gallery_scroll=scroll;clips_layout.addWidget(scroll,1)
  self.export_details=QTableWidget(0,6)
  self.export_details.setHorizontalHeaderLabels(['Export','Clip','Start','End','Duration','Filename'])
  self.export_details.setSelectionBehavior(QAbstractItemView.SelectRows)
  self.export_details.setSelectionMode(QAbstractItemView.SingleSelection)
  self.export_details.setEditTriggers(QAbstractItemView.DoubleClicked|QAbstractItemView.EditKeyPressed)
  self.export_details.setAlternatingRowColors(True)
  self.export_details.verticalHeader().setVisible(False)
  self.export_details.verticalHeader().setDefaultSectionSize(29)
  header=self.export_details.horizontalHeader()
  header.setSectionResizeMode(QHeaderView.Interactive)
  header.setSectionResizeMode(5,QHeaderView.Stretch)
  self.export_details.setColumnWidth(0,66);self.export_details.setColumnWidth(1,70)
  self.export_details.setColumnWidth(2,95);self.export_details.setColumnWidth(3,95);self.export_details.setColumnWidth(4,90)
  self.export_details.itemSelectionChanged.connect(self.export_details_selection_changed)
  self.export_details.itemChanged.connect(self.export_details_item_changed)
  clips_layout.addWidget(self.export_details,1)
  self.export_gallery_scroll.setVisible(self.export_view_mode.currentText()=='Gallery')
  self.export_details.setVisible(self.export_view_mode.currentText()=='Details')
  self.export_workspace.addWidget(clips_page)
  # Embedded clip player; positions are absolute media milliseconds, bounded by the selected segment.
  preview=QGroupBox('SELECTED CLIP  •  Preview');pv=QVBoxLayout(preview)
  media_row=QHBoxLayout()
  self.export_video=QVideoWidget();self.export_video.setMinimumSize(260,150);self.export_video.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
  media_row.addWidget(self.export_video,2)
  still_col=QVBoxLayout();still_col.addWidget(QLabel('Opening frame'))
  self.export_still=QLabel('Select a clip to load its still image')
  self.export_still.setAlignment(Qt.AlignCenter);self.export_still.setMinimumSize(145,110)
  self.export_still.setObjectName('exportStill')
  self.export_still.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
  still_col.addWidget(self.export_still,1);media_row.addLayout(still_col,1);pv.addLayout(media_row)
  playback=QHBoxLayout()
  self.export_play=QPushButton('▶ Play');self.export_play.clicked.connect(self.toggle_export_play)
  playback.addWidget(self.export_play)
  self.export_rewind=QPushButton('↶ 5s');self.export_rewind.clicked.connect(lambda:self.seek_export_relative(-5000));playback.addWidget(self.export_rewind)
  self.export_forward=QPushButton('5s ↷');self.export_forward.clicked.connect(lambda:self.seek_export_relative(5000));playback.addWidget(self.export_forward)
  self.export_seek=QSlider(Qt.Horizontal);self.export_seek.setRange(0,1000)
  self.export_seek.sliderMoved.connect(self.seek_export_slider);playback.addWidget(self.export_seek,1)
  self.export_clock=QLabel('00:00 / 00:00');playback.addWidget(self.export_clock)
  pv.addLayout(playback)
  self.export_player_status=QLabel('Select a clip, then press Play. Scrub or skip without watching the whole clip.')
  self.export_player_status.setWordWrap(True);pv.addWidget(self.export_player_status)
  self.export_workspace.addWidget(preview)
  self.export_workspace.setChildrenCollapsible(False)
  self.export_workspace.setHandleWidth(8)
  self.export_workspace.setStretchFactor(0,3);self.export_workspace.setStretchFactor(1,2)
  self.export_workspace.setSizes(self.prefs.get('export_workspace_sizes',[720,500]))
  self.export_workspace.splitterMoved.connect(lambda pos,index:self.save_ui_preference('export_workspace_sizes',self.export_workspace.sizes()))
  lay.addWidget(self.export_workspace,1)
  self.media_player=QMediaPlayer(self)
  self.media_audio=QAudioOutput(self);self.media_player.setAudioOutput(self.media_audio)
  self.media_player.setVideoOutput(self.export_video)
  self.media_player.positionChanged.connect(self.export_position_changed)
  self.media_player.mediaStatusChanged.connect(self.export_media_status)
  self.media_player.errorOccurred.connect(self.export_media_error)
  self.media_player.playbackStateChanged.connect(self.export_playback_changed)
  self.export_bounds=(0,0);self.export_media_path=None;self.export_still_process=None
  self.export_still_cache={}  # bounded, keyed by source file and opening-frame time
  self.export_management=QTabWidget();self.export_management.setDocumentMode(True)
  settings_page=QWidget();settings_layout=QVBoxLayout(settings_page)
  controls=QHBoxLayout();self.output_dir=QLineEdit();self.output_dir.setPlaceholderText('Export folder');controls.addWidget(self.output_dir,1)
  choose=QPushButton('Browse…');choose.clicked.connect(self.choose_output);controls.addWidget(choose)
  self.export_mode=QComboBox();self.export_mode.addItems(['Accurate','Fast copy'])
  self.export_mode.setToolTip('Accurate re-encodes for precise boundaries; Fast copy is quicker but may shift to keyframes')
  controls.addWidget(self.export_mode)
  self.fast_copy_note=QLabel('Fast Copy prioritizes speed; cut boundaries may shift to keyframes. Accurate re-encodes for more precise cuts. Export verification checks durations, not exact first/last frames.')
  self.fast_copy_note.setObjectName('muted');self.fast_copy_note.setWordWrap(True)
  self.export_mode.currentTextChanged.connect(lambda mode:self.fast_copy_note.setVisible(mode!='Accurate'))
  settings_layout.addLayout(controls)
  settings_layout.addWidget(self.fast_copy_note);self.fast_copy_note.hide()
  preset_row=QHBoxLayout();preset_row.addWidget(QLabel('Encoding preset'))
  self.export_preset=QComboBox();self.export_preset.addItems(['Balanced','High Quality','Smaller File','Fast Encode','Original Streams (Fast copy)'])
  self.export_preset.setCurrentText(self.prefs.get('export_preset','Balanced'))
  self.export_preset.currentTextChanged.connect(self.preset_changed)
  preset_row.addWidget(self.export_preset);preset_row.addStretch();settings_layout.addLayout(preset_row)
  settings_layout.addStretch();self.export_management.addTab(settings_page,'Settings')
  queue_page=QWidget();queue_layout=QVBoxLayout(queue_page)
  self.queue_list=QListWidget();self.queue_list.setMinimumHeight(170);self.queue_list.setAlternatingRowColors(True);self.queue_list.setSpacing(2);self.queue_list.setStyleSheet('QListWidget::item {padding:5px 7px;}');self.queue_list.setDragDropMode(QAbstractItemView.InternalMove);self.queue_list.model().rowsMoved.connect(self.queue_rows_moved);queue_layout.addWidget(QLabel('BATCH QUEUE  •  Drag jobs to reorder'));queue_layout.addWidget(self.queue_list,1)
  queue_controls=QHBoxLayout()
  add_queue=QPushButton('Add Clips');add_queue.clicked.connect(self.add_export_queue);queue_controls.addWidget(add_queue)
  self.queue_run_btn=QPushButton('Run Queue');self.queue_run_btn.clicked.connect(self.run_export_queue);queue_controls.addWidget(self.queue_run_btn)
  self.queue_pause_btn=QPushButton('Pause After Clip');self.queue_pause_btn.setCheckable(True);self.queue_pause_btn.toggled.connect(self.set_queue_pause);queue_controls.addWidget(self.queue_pause_btn)
  stop_queue=QPushButton('■ Stop');stop_queue.clicked.connect(self.stop_export_queue);queue_controls.addWidget(stop_queue)
  queue_layout.addLayout(queue_controls)
  queue_controls=QHBoxLayout()
  remove_queue=QPushButton('Remove');remove_queue.clicked.connect(self.remove_export_queue);queue_controls.addWidget(remove_queue)
  retry_queue=QPushButton('Retry Failed');retry_queue.clicked.connect(self.retry_failed_queue);queue_controls.addWidget(retry_queue)
  clear_queue=QPushButton('Clear Queue');clear_queue.clicked.connect(self.clear_export_queue);queue_controls.addWidget(clear_queue)
  history_btn=QPushButton('History');history_btn.clicked.connect(self.show_export_history);queue_controls.addWidget(history_btn)
  queue_layout.addLayout(queue_controls)
  self.export_eta=QLabel('No export running');queue_layout.addWidget(self.export_eta);self.queue_summary=QLabel('');queue_layout.addWidget(self.queue_summary);self.refresh_export_queue()
  self.export_management.addTab(queue_page,'Queue && History')
  self.export_management.setCurrentIndex(max(0,min(1,int(self.prefs.get('export_management_tab',0)))))
  self.export_management.currentChanged.connect(lambda index:self.save_ui_preference('export_management_tab',index))
  self.export_management.setMinimumHeight(345);self.export_management.setMaximumHeight(460)
  lay.addWidget(self.export_management)
  self.output_dir.setText(self.project_export_folder())
  self.export_progress_heading=QLabel('EXPORT PROGRESS');self.export_progress_heading.setObjectName('muted');lay.addWidget(self.export_progress_heading)
  self.progress=QProgressBar();self.progress.setValue(0);self.progress.setToolTip('Overall progress of the current export');lay.addWidget(self.progress)
  row=QHBoxLayout();self.play_btn=QPushButton('▶  Play Selected Clip Here');self.play_btn.clicked.connect(self.play_selected);row.addWidget(self.play_btn)
  self.export_btn=QPushButton('Export Included Clips');self.export_btn.setObjectName('primary');self.export_btn.clicked.connect(self.export_native);row.addWidget(self.export_btn)
  self.cancel_export_btn=QPushButton('Cancel Export');self.cancel_export_btn.setEnabled(False);self.cancel_export_btn.clicked.connect(self.cancel_export);row.addWidget(self.cancel_export_btn)
  self.results_btn=QPushButton('View Export Results');self.results_btn.setEnabled(False);self.results_btn.clicked.connect(self.show_export_results);row.addWidget(self.results_btn)
  row.addStretch();lay.addLayout(row)
  self.last_export_checks=[]
  self.export_run_total=0;self.export_run_completed=0;self.export_run_failed=0
  scroll=QScrollArea()
  scroll.setWidgetResizable(True)
  scroll.setFrameShape(QFrame.NoFrame)
  scroll.setWidget(page)
  self.stack.addWidget(scroll)
 def build_menu(self):
  file=self.menuBar().addMenu('File');file.addAction('Project Dashboard',self.show_dashboard);act=file.addAction('Open Video…');act.triggered.connect(self.choose)
  file.addSeparator();file.addAction('Open Project…',self.open_project);self.recent_menu=file.addMenu('Recent Projects');file.addAction('Reopen Last Project',self.reopen_last_project);file.addAction('Save Project',self.save_project);file.addAction('Save Project As…',lambda:self.save_project(as_new=True));file.addSeparator();file.addAction('Close Project',self.close_project);file.addAction('Exit',self.close);self.refresh_recent_menu()
  review=self.menuBar().addMenu('Review');review.addAction('Refresh Saved Cuts',self.read_recovery);review.addAction('Scan Recording',self.scan_native);review.addAction('Start Fresh / Clear Recovery',self.clear_video_recovery);
  export=self.menuBar().addMenu('Export');export.addAction('Export Selected Clips',self.export_native);export.addAction('Add Clips to Queue',self.add_export_queue);export.addAction('Run Queue',self.run_export_queue);export.addAction('Export History',self.show_export_history)
  settings=self.menuBar().addMenu('Settings');settings.addAction('Preferences…',self.show_settings)
  helpmenu=self.menuBar().addMenu('Help');helpmenu.addAction('Check for Updates…',self.check_for_updates);channel_menu=helpmenu.addMenu('Update Channel');self.stable_channel_action=channel_menu.addAction('Stable releases');self.prerelease_channel_action=channel_menu.addAction('Include pre-releases');self.stable_channel_action.setCheckable(True);self.prerelease_channel_action.setCheckable(True);self.stable_channel_action.triggered.connect(lambda:self.set_update_channel('stable'));self.prerelease_channel_action.triggered.connect(lambda:self.set_update_channel('prerelease'));self.refresh_update_channel_menu();helpmenu.addAction('Save Diagnostics Report…',self.save_diagnostics_report);helpmenu.addAction('About…',lambda:QMessageBox.information(self,'About Commercial Splitter','Commercial Splitter v4.9.1\n\nTimeline editing, detection review, project management, and verified clip exports.'))
 def refresh_update_channel_menu(self):
  channel=self.prefs.get('update_channel','stable')
  self.stable_channel_action.setChecked(channel=='stable')
  self.prerelease_channel_action.setChecked(channel=='prerelease')
 def set_update_channel(self,channel):
  self.prefs['update_channel']=channel
  self.save_preferences(self.prefs)
  self.refresh_update_channel_menu()
 def check_for_updates(self):
  if getattr(self,'release_checker',None) is not None and self.release_checker.isRunning():return
  self.release_checker=ReleaseCheckWorker(self.prefs.get('update_channel','stable'),self)
  self.release_checker.result.connect(self.show_release_result)
  self.release_checker.start()
  self.status.setText('Checking GitHub for updates…')
 def show_release_result(self,data):
  if 'error' in data:
   self.status.setText('Update check unavailable')
   QMessageBox.information(self,'Check for Updates',data['error']);return
  version=data['version']
  current=(4,9,1)
  remote=tuple(map(int,version.split('.')))
  if remote<=current:
   self.status.setText('Commercial Splitter is up to date')
   QMessageBox.information(self,'Check for Updates',f"You are running 4.9.1. Latest {data['channel']} release: {version}.")
   return
  self.status.setText('Commercial Splitter '+version+' is available')
  message=f'Commercial Splitter {version} is available ({"pre-release" if data["prerelease"] else "stable"}).\n\n'+data['notes'][:900]+'\n\nOpen its official GitHub release page?\n\nUpdates are not installed automatically in this version.'
  if QMessageBox.question(self,'Update Available',message,QMessageBox.Yes|QMessageBox.No)==QMessageBox.Yes:
   QDesktopServices.openUrl(QUrl(data['url']))
 def save_diagnostics_report(self):
  # Local-only report. Keep each field on its own line and group related data.
  suggested=APPDATA/('Commercial_Splitter_Diagnostics_'+time.strftime('%Y%m%d_%H%M%S')+'.txt')
  path,_=QFileDialog.getSaveFileName(self,'Save Diagnostics Report',str(suggested),'Text reports (*.txt)')
  if not path:return
  try:
   video=Path(self.video) if self.video else None
   lines=['COMMERCIAL SPLITTER — DIAGNOSTICS REPORT',
          '='*58,
          'Generated: '+time.strftime('%Y-%m-%d %H:%M:%S'),
          'Application version: 4.7.22',
          '',
          'SYSTEM AND TOOLS','-'*58,
          'Platform: '+sys.platform,
          'Python: '+sys.version.split()[0],
          'PySide6: '+__import__('PySide6').__version__,
          'FFmpeg: '+str(tool('ffmpeg') or 'NOT FOUND'),
          'FFprobe: '+str(tool('ffprobe') or 'NOT FOUND'),
          '',
          'PROJECT AND RECORDING','-'*58,
          'Source video: '+str(video or '(none)'),
          'Source exists: '+str(bool(video and video.is_file())),
          'Duration (seconds): '+str(round(self.duration,3)),
          'FPS: '+str(round(self.fps,5)),
          'Saved project: '+str(self.project_path or '(none)'),
          'Project folder: '+str(self.prefs.get('project_library_folder','')),
          '',
          'CUT DETECTION','-'*58,
          'Candidates: '+str(len(self.candidates)),
          'Accepted boundaries: '+str(len(self.cuts)),
          'Pending candidates: '+str(sum(not c.get('keep') and not c.get('rejected') for c in self.candidates)),
          'Rejected candidates: '+str(sum(bool(c.get('rejected')) for c in self.candidates)),
          'Black intervals: '+str(len(self.auto_black_intervals)),
          'Silence intervals: '+str(len(self.auto_silence_intervals)),
          'Scene transitions: '+str(len(self.auto_visual_times)),
          '',
          'EXPORT AND ACTIVITY','-'*58,
          'Export queue length: '+str(len(self.export_queue)),
          'Background task busy: '+str(self.busy),
          '',
          'ACCEPTED SPLIT TIMESTAMPS','-'*58]
   if self.cuts:
    lines.extend(f'  {i:3d}. {fmt(t)}' for i,t in enumerate(sorted(self.cuts),1))
   else:lines.append('  (none)')
   lines.extend(['','RECENT APPLICATION LOG (LAST 80 LINES)','-'*58])
   log=APPDATA/'qt_load_diagnostics.log'
   if log.is_file():
    with log.open('rb') as f:
     f.seek(0,2);f.seek(max(0,f.tell()-32768))
     recent=f.read().decode('utf-8','replace').splitlines()[-80:]
    lines.extend(recent or ['(log empty)'])
   else:lines.append('(no log file)')
   destination=Path(path);destination.parent.mkdir(parents=True,exist_ok=True)
   destination.write_text('\n'.join(lines)+'\n',encoding='utf-8')
   QMessageBox.information(self,'Diagnostics saved','Report saved to:\n'+str(destination)+'\n\nThe report includes local file paths and log entries. Review before sharing.')
  except Exception as exc:
   QMessageBox.warning(self,'Diagnostics error','Could not save the report:\n'+str(exc))

 def set_timeline_playback_position(self,position):
  # Move the same widget, retaining all button connections and playback state.
  layout=self.timeline_playback_layout
  layout.removeWidget(self.timeline_playback_bar)
  if position=='Bottom':
   # Immediately below the timeline strip, before zoom and editing controls.
   layout.insertWidget(layout.indexOf(self.timeline_view)+1,self.timeline_playback_bar)
  else:
   layout.insertWidget(2,self.timeline_playback_bar)
  self.timeline_playback_bar.show()
 def load_preferences(self):
  defaults={'shortcuts':{},'default_export_folder':r'D:\Commercial Exports','recording_subfolders':True,'theme':'dark','default_export_mode':'Accurate','autosave_enabled':True,'autosave_minutes':5,'recent_projects':[],'project_library_folder':str(Path.home()/'Documents'/'Commercial Splitter Projects'),'startup_restore':False,'pinned_projects':[],'export_preset':'Balanced','export_history':[],'export_queue':[],'failed_export_jobs':[],'detection_profiles':{},'active_detection_profile':'Balanced','compact_review':True,'timeline_organizer_visible':False,'timeline_tool_tab':0,'export_workspace_tab':0,'export_management_tab':0,'export_gallery_view':'Gallery','main_window_geometry':'','export_workspace_sizes':[720,500],'cut_inspector_visible':True,'confirm_inspector_cut_delete':False,'cut_inspector_widths':[790,290],'timeline_playback_position':'Top','timeline_clip_wave_overlay':True,'timeline_wave_mode':0,'update_channel':'stable'}
  try:
   data=json.loads(PREFS_FILE.read_text(encoding='utf-8'))
   if isinstance(data,dict):defaults.update({k:v for k,v in data.items() if k in defaults})
  except (OSError,ValueError,TypeError):pass
  if defaults['theme'] not in ('dark','light','system'):defaults['theme']='dark'
  if defaults['update_channel'] not in ('stable','prerelease'):defaults['update_channel']='stable'
  if defaults['default_export_mode'] not in ('Accurate','Fast copy'):defaults['default_export_mode']='Accurate'
  defaults['recording_subfolders']=bool(defaults['recording_subfolders'])
  defaults['autosave_enabled']=bool(defaults['autosave_enabled'])
  if defaults['autosave_minutes'] not in (1,5,10,15):defaults['autosave_minutes']=5
  if not isinstance(defaults['recent_projects'],list):defaults['recent_projects']=[]
  defaults['recent_projects']=[x for x in defaults['recent_projects'] if isinstance(x,str)][:10]
  if not isinstance(defaults['pinned_projects'],list):defaults['pinned_projects']=[]
  defaults['pinned_projects']=[p for p in defaults['pinned_projects'] if isinstance(p,str)]
  defaults['startup_restore']=bool(defaults['startup_restore'])
  defaults['confirm_inspector_cut_delete']=bool(defaults['confirm_inspector_cut_delete'])
  for key,fallback in (('cut_inspector_widths',[790,290]),('export_workspace_sizes',[720,500])):
   value=defaults.get(key)
   if not isinstance(value,list) or len(value)!=2 or any(type(x) is not int or x<0 or x>10000 for x in value):
    defaults[key]=fallback
  if defaults.get('export_gallery_view') not in ('Gallery','Details'):defaults['export_gallery_view']='Gallery'
  if not isinstance(defaults.get('main_window_geometry'),str):defaults['main_window_geometry']=''
  if not isinstance(defaults.get('project_library_folder'),str):defaults['project_library_folder']=str(Path.home()/'Documents'/'Commercial Splitter Projects')
  return defaults
 def save_preferences(self,values):
  PREFS_FILE.parent.mkdir(parents=True,exist_ok=True)
  tmp=PREFS_FILE.with_suffix('.tmp')
  tmp.write_text(json.dumps(values,indent=2),encoding='utf-8')
  os.replace(tmp,PREFS_FILE)
 def project_export_folder(self):
  if not self.video or not self.prefs['recording_subfolders']:return self.default_export_root
  return str(Path(self.default_export_root)/safe_folder_name(Path(self.video).stem))
 def shortcut_definitions(self):
  return [
   ('open','Open video','Ctrl+O',self.choose),
   ('settings','Open preferences','Ctrl+,',self.show_settings),
   ('import','Go to Import','Ctrl+1',lambda:self.go(0)),
   ('review','Go to Review','Ctrl+2',lambda:self.go(1)),
   ('timeline','Go to Timeline','Ctrl+3',lambda:self.go(2)),
   ('export_tab','Go to Export','Ctrl+4',lambda:self.go(3)),
   ('play','Play / pause','Space',self.workspace_play_pause),
   ('preview_around_split','Preview around selected split','P',self.timeline_preview_around_split),
   ('frame_back','Previous frame','Left',lambda:self.timeline_step(-1)),
   ('frame_forward','Next frame','Right',lambda:self.timeline_step(1)),
   ('add','Add split','Ctrl+K',self.timeline_add),
   ('remove','Remove selected split','Ctrl+Shift+K',self.timeline_remove),
   ('undo','Undo timeline edit','Ctrl+Z',self.timeline_undo),
   ('redo','Redo timeline edit','Ctrl+Y',self.timeline_redo),
   ('clip_prev','Previous clip','Alt+Left',lambda:self.timeline_jump_relative(-1)),
   ('clip_next','Next clip','Alt+Right',lambda:self.timeline_jump_relative(1)),
   ('clip_start','Jump to clip start','Ctrl+J',self.timeline_jump_to_selected),
   ('zoom_in','Zoom in','Ctrl+Plus',lambda:self.timeline_zoom.setValue(min(self.timeline_zoom.maximum(),self.timeline_zoom.value()+1))),
   ('zoom_out','Zoom out','Ctrl+Minus',lambda:self.timeline_zoom.setValue(max(0,self.timeline_zoom.value()-1))),
   ('zoom_fit','Fit entire video','Ctrl+0',lambda:self.timeline_zoom.setValue(0)),
  ]
 def setup_shortcuts(self):
  self.custom_shortcuts={}
  for key,label,default,callback in self.shortcut_definitions():
   shortcut=QShortcut(self)
   shortcut.setContext(Qt.WindowShortcut)
   shortcut.activated.connect(callback)
   self.custom_shortcuts[key]=shortcut
  self.edit_delete_shortcut=QShortcut(QKeySequence(Qt.Key_Delete),self)
  self.edit_delete_shortcut.setContext(Qt.WindowShortcut)
  self.edit_delete_shortcut.activated.connect(self.delete_selected_edit)
  self.apply_shortcuts()
 def delete_selected_edit(self):
  if not self.video or self.busy or self.stack.currentIndex()!=2:return
  focus=QApplication.focusWidget()
  if isinstance(focus,(QLineEdit,QTextEdit,QPlainTextEdit,QSpinBox,QDoubleSpinBox,QComboBox)):
   return  # Preserve Delete for editable fields
  if focus is self.inspector_list or (focus and self.inspector_list.isAncestorOf(focus)):
   self.inspector_delete_selected_cut();return
  if focus is self.candidate_list or (focus and self.candidate_list.isAncestorOf(focus)):
   self.delete_review_candidate();return
  if focus is self.accepted_list or (focus and self.accepted_list.isAncestorOf(focus)):
   self.delete_accepted_cut();return
  if self.timeline_review_tabs.currentIndex()==0:
   self.timeline_remove()  # Uses the highlighted split marker, not the selected clip.
 def apply_shortcuts(self):
  saved=self.prefs.get('shortcuts',{})
  for key,label,default,callback in self.shortcut_definitions():
   self.custom_shortcuts[key].setKey(QKeySequence(saved.get(key,default)))
 def shortcut_allowed(self,key):
  # Playback and editing keys must not interfere with normal text editing.
  return True
 def show_settings(self):
  dialog=QDialog(self);dialog.setWindowTitle('Preferences');dialog.resize(520,340)
  layout=QVBoxLayout(dialog);tabs=QTabWidget();layout.addWidget(tabs)
  general=QWidget();gl=QVBoxLayout(general)
  gl.addWidget(QLabel('Default project folder (scanned on startup)'))
  project_folder_row=QHBoxLayout()
  project_folder_edit=QLineEdit(self.prefs.get('project_library_folder',''))
  project_folder_row.addWidget(project_folder_edit)
  project_folder_browse=QPushButton('Browse…')
  project_folder_browse.clicked.connect(lambda:self.browse_default_folder(project_folder_edit,dialog))
  project_folder_row.addWidget(project_folder_browse)
  gl.addLayout(project_folder_row)
  gl.addWidget(QLabel('Default export folder'))
  folder_row=QHBoxLayout();folder_edit=QLineEdit(self.default_export_root);folder_row.addWidget(folder_edit)
  browse=QPushButton('Browse…');folder_row.addWidget(browse)
  browse.clicked.connect(lambda:self.browse_default_folder(folder_edit,dialog))
  gl.addLayout(folder_row)
  subfolders=QCheckBox('Create a separate folder for each recording');subfolders.setChecked(self.prefs['recording_subfolders']);gl.addWidget(subfolders)
  confirm_inspector_delete=QCheckBox('Confirm before deleting accepted cuts in Cut Inspector')
  confirm_inspector_delete.setChecked(self.prefs.get('confirm_inspector_cut_delete',False))
  gl.addWidget(confirm_inspector_delete)
  gl.addWidget(QLabel('Timeline playback controls position'))
  playback_position=QComboBox();playback_position.addItems(['Top','Bottom'])
  playback_position.setCurrentText(self.prefs.get('timeline_playback_position','Top'))
  gl.addWidget(playback_position)
  gl.addWidget(QLabel('Audio waveform display'))
  waveform_mode=QComboBox();waveform_mode.addItems(['On timeline (inside clips)','Above timeline (separate track)','Off'])
  waveform_mode.setCurrentIndex(self.timeline_wave_mode.currentIndex())
  gl.addWidget(waveform_mode)
  gl.addStretch();tabs.addTab(general,'General')
  appearance=QWidget();al=QVBoxLayout(appearance);al.addWidget(QLabel('Application theme'))
  theme=QComboBox();theme.addItem('Dark','dark');theme.addItem('Light','light');theme.addItem('Follow Windows','system')
  theme.setCurrentIndex(max(0,theme.findData(self.prefs['theme'])));al.addWidget(theme);al.addStretch();tabs.addTab(appearance,'Appearance')
  export=QWidget();el=QVBoxLayout(export);el.addWidget(QLabel('Default export mode'))
  mode=QComboBox();mode.addItems(['Accurate','Fast copy']);mode.setCurrentText(self.prefs['default_export_mode']);el.addWidget(mode)
  info=QLabel('Fast Copy may include neighboring frames at cut boundaries.');info.setWordWrap(True);el.addWidget(info);el.addStretch();tabs.addTab(export,'Export')
  shortcut_tab=QWidget();sl=QVBoxLayout(shortcut_tab)
  note=QLabel('Click a shortcut and press the new key combination. Clear to disable it. Changes take effect when you save.')
  note.setWordWrap(True);sl.addWidget(note)
  shortcut_scroll=QScrollArea();shortcut_scroll.setWidgetResizable(True)
  shortcut_inner=QWidget();shortcut_form=QFormLayout(shortcut_inner)
  shortcut_edits={}
  for key,label,default,callback in self.shortcut_definitions():
   editor=QKeySequenceEdit(QKeySequence(self.prefs.get('shortcuts',{}).get(key,default)))
   editor.setClearButtonEnabled(True)
   editor.setToolTip('Default: '+default)
   shortcut_form.addRow(label,editor);shortcut_edits[key]=editor
  shortcut_scroll.setWidget(shortcut_inner);sl.addWidget(shortcut_scroll,1)
  reset_shortcuts=QPushButton('Restore Default Shortcuts')
  def restore_defaults():
   for key,label,default,callback in self.shortcut_definitions():
    shortcut_edits[key].setKeySequence(QKeySequence(default))
  reset_shortcuts.clicked.connect(restore_defaults);sl.addWidget(reset_shortcuts)
  tabs.addTab(shortcut_tab,'Shortcuts')
  autosave_tab=QWidget();asl=QVBoxLayout(autosave_tab)
  autosave_enabled=QCheckBox('Automatically save an open project');autosave_enabled.setChecked(self.prefs['autosave_enabled']);asl.addWidget(autosave_enabled)
  asl.addWidget(QLabel('Auto-save interval'))
  autosave_interval=QComboBox()
  for n in (1,5,10,15):autosave_interval.addItem(f'{n} minute'+('' if n==1 else 's'),n)
  autosave_interval.setCurrentIndex(max(0,autosave_interval.findData(self.prefs['autosave_minutes'])))
  asl.addWidget(autosave_interval)
  note=QLabel('Auto-save requires a saved .csproj project. The previous project file is backed up as .csproj.bak. Unsaved projects still prompt on closing.')
  note.setWordWrap(True);asl.addWidget(note);asl.addStretch();tabs.addTab(autosave_tab,'Auto-Save')
  startup_tab=QWidget();stl=QVBoxLayout(startup_tab)
  restore_on_start=QCheckBox('Reopen the last project when Commercial Splitter starts');restore_on_start.setChecked(self.prefs.get('startup_restore',False));stl.addWidget(restore_on_start)
  stl.addWidget(QLabel('The File menu keeps a list of up to 10 recent projects.'));stl.addStretch();tabs.addTab(startup_tab,'Startup')
  buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);layout.addWidget(buttons)
  buttons.rejected.connect(dialog.reject)
  def save():
   new=dict(self.prefs);new.update(confirm_inspector_cut_delete=confirm_inspector_delete.isChecked(),project_library_folder=project_folder_edit.text().strip(),default_export_folder=folder_edit.text().strip(),recording_subfolders=subfolders.isChecked(),theme=theme.currentData(),default_export_mode=mode.currentText(),autosave_enabled=autosave_enabled.isChecked(),autosave_minutes=autosave_interval.currentData(),startup_restore=restore_on_start.isChecked(),timeline_playback_position=playback_position.currentText(),timeline_wave_mode=waveform_mode.currentIndex())
   sequences={}
   used={}
   for key,label,default,callback in self.shortcut_definitions():
    value=shortcut_edits[key].keySequence().toString(QKeySequence.PortableText)
    canonical=QKeySequence(value).toString(QKeySequence.PortableText)
    if canonical and canonical in used:
     QMessageBox.warning(dialog,'Duplicate shortcut',f'{label} conflicts with {used[canonical]} ({canonical}).');return
    if canonical:used[canonical]=label
    sequences[key]=canonical
   new['shortcuts']=sequences
   if not new['project_library_folder']:
    QMessageBox.warning(dialog,'Invalid folder','Choose a default project folder.');return
   if not new['default_export_folder']:
    QMessageBox.warning(dialog,'Invalid folder','Choose a default export folder.');return
   try:self.save_preferences(new)
   except OSError as exc:QMessageBox.warning(dialog,'Settings error',str(exc));return
   old=self.project_export_folder();old_default=self.prefs['default_export_mode']
   self.prefs=new;self.default_export_root=new['default_export_folder']
   if self.output_dir.text().strip()==old:self.output_dir.setText(self.project_export_folder())
   if self.export_mode.currentText()==old_default:self.export_mode.setCurrentText(new['default_export_mode'])
   self.timeline_wave_mode.setCurrentIndex(new['timeline_wave_mode'])
   self.autosave_elapsed=0;self.set_timeline_playback_position(new['timeline_playback_position']);self.apply_theme();self.apply_shortcuts();self.status.setText('Preferences saved');self.refresh_dashboard();dialog.accept()
  buttons.accepted.connect(save)
  dialog.exec()
 def browse_default_folder(self,edit,parent):
  path=QFileDialog.getExistingDirectory(parent,'Choose default export folder',edit.text() or str(Path.home()))
  if path:edit.setText(path)
 def apply_theme(self):
  theme=self.prefs['theme']
  if theme=='system':
   try:theme='dark' if QApplication.styleHints().colorScheme()==Qt.Dark else 'light'
   except (AttributeError,TypeError):theme='dark'
  QApplication.instance().setStyleSheet(STYLE if theme=='dark' else LIGHT_STYLE)
 def combine_timeline_review(self):
  """Place the existing Review UI inside Timeline without rebuilding its controls.

  Preserve the original stack indices for all legacy actions, recovery,
  export refreshes, and shortcuts.
  """
  review=self.stack.widget(1)
  timeline=self.stack.widget(2)
  self.stack.removeWidget(review)
  self.stack.insertWidget(1,QWidget())  # Legacy review index redirects to timeline.
  self.stack.removeWidget(timeline)
  workspace=QWidget()
  layout=QVBoxLayout(workspace)
  layout.setContentsMargins(0,0,0,0)
  layout.setSpacing(5)
  self.timeline_review_tabs=QTabWidget()
  self.timeline_review_tabs.setDocumentMode(True)
  self.timeline_review_tabs.addTab(timeline,'Timeline Editor')
  self.timeline_review_tabs.setTabToolTip(0,'Click or drag the timeline to scrub. Drag a yellow marker to move a cut. Add or remove splits without modifying the original recording.')
  self.timeline_review_tabs.addTab(review,'Review Suggested Cuts')
  self.timeline_review_tabs.setTabToolTip(1,'Review detected candidates here; scanning and detection profiles are under Import & Scan.')
  layout.addWidget(self.timeline_review_tabs)
  self.stack.insertWidget(2,workspace)
  self.timeline_review_tabs.currentChanged.connect(self.timeline_review_tab_changed)
  self.timeline_review_tabs.setCurrentIndex(0)

 def toggle_cut_inspector(self,button):
  visible=not self.cut_inspector_panel.isVisible()
  self.cut_inspector_panel.setVisible(visible)
  button.setText('Hide Cut Inspector' if visible else 'Show Cut Inspector')
  self.save_ui_preference('cut_inspector_visible',visible)
  if visible:self.inspector_refresh()

 def inspector_refresh(self,focus=None):
  if not hasattr(self,'inspector_list'):return
  if focus is None:
   item=self.inspector_list.currentItem()
   focus=item.data(Qt.UserRole) if item else None
  self.inspector_list.blockSignals(True)
  self.inspector_list.clear()
  selected=-1
  pending=0
  for index in sorted(range(len(self.candidates)),key=lambda i:float(self.candidates[i].get('time',0))):
   c=self.candidates[index]
   accepted=bool(c.get('keep') and not c.get('rejected'))
   rejected=bool(c.get('rejected'))
   # Show confident automatic boundaries AND user-created manual splits.
   # Unaccepted low-confidence suggestions remain in Review; accepted ones are real boundaries.
   confidence=str(c.get('confidence','')).lower()
   is_manual=confidence=='manual' or str(c.get('source','')).lower().startswith('timeline manual')
   if not accepted and confidence not in ('high','medium') and not is_manual:continue
   # Rejected/deleted markers belong in Review history, not the active Cut Inspector.
   # Keep pending medium/high suggestions visible until the user decides.
   if rejected:continue
   if not accepted and not rejected:pending+=1
   state='✎ Manual' if is_manual and accepted else ('✓ Accepted' if accepted else ('× Rejected' if rejected else ('★ Recommended' if c.get('suggested') else '○ Review Only')))
   item=QListWidgetItem(f'{fmt(float(c.get("time",0)))}   {state}  ·  {str(c.get("confidence","")).title()}')
   item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
   item.setSizeHint(QSize(190,33))
   item.setData(Qt.UserRole,index)
   item.setToolTip(str(c.get('reason') or c.get('source') or 'No detection evidence recorded'))
   light=self.prefs.get('theme')=='light'
   if self.prefs.get('theme')=='system':
    try:light=QApplication.styleHints().colorScheme()!=Qt.Dark
    except (AttributeError,TypeError):light=False
   color=('#a9d4ff' if light else '#82bfff') if accepted and is_manual else (
    ('#e2c6ff' if light else '#d6bcff') if accepted and confidence=='low' else (
    ('#8ee8c9' if light else '#58d6b3') if accepted else ('#ffe19a' if light else '#f1c477')))
   item.setForeground(QBrush(QColor(color)))
   item.setData(Qt.UserRole+1,color)
   self.inspector_list.addItem(item)
   if index==focus:selected=self.inspector_list.count()-1
  self.inspector_list.blockSignals(False)
  placed=sum(bool(c.get('keep')) and not c.get('rejected') and str(c.get('confidence','')).lower() in ('high','medium') for c in self.candidates)
  low_accepted=sum(bool(c.get('keep')) and not c.get('rejected') and str(c.get('confidence','')).lower()=='low' for c in self.candidates)
  manual=sum(bool(c.get('keep')) and not c.get('rejected') and (str(c.get('confidence','')).lower()=='manual' or str(c.get('source','')).lower().startswith('timeline manual')) for c in self.candidates)
  self.inspector_progress.setText(f'✓ {placed} accepted auto  ·  ◇ {low_accepted} accepted low  ·  ✎ {manual} manual\n○ {pending} awaiting review  ·  {self.inspector_list.count()} visible')
  # Rebuilding the inspector must not jump playback to candidate zero.
  # Restore a previous explicit selection without emitting navigation signals.
  self.inspector_list.blockSignals(True)
  if selected>=0:self.inspector_list.setCurrentRow(selected)
  self.inspector_list.blockSignals(False)
  if selected<0:self.inspector_detail.setText('Select a cut to inspect its detection evidence.' if self.inspector_list.count() else 'No active cuts yet. Scan or add a manual cut.')

 def timeline_clear_current_preview(self):
  # A paused FFmpeg still belongs to the previous recording until explicitly cleared.
  self.timeline_still_token+=1
  if self.timeline_paused_still_timer.isActive():self.timeline_paused_still_timer.stop()
  old=self.timeline_still_proc;self.timeline_still_proc=None
  if old is not None:
   old.blockSignals(True)
   if old.state()!=QProcess.NotRunning:old.kill()
   old.deleteLater()
  self.timeline_current_original=None
  self.timeline_still.clear()
  self.timeline_still.setText('No recording loaded' if not self.video else 'Loading new recording…')
  self.timeline_video_stack.setCurrentIndex(1)

 def timeline_show_inspector_still(self,position):
  # QMediaPlayer can show black on first seek, particularly for VP9/WebM.
  # FFmpeg supplies an independent exact-position still until Play is pressed.
  self.timeline_still_token+=1
  token=self.timeline_still_token
  old=self.timeline_still_proc
  self.timeline_still_proc=None
  if old is not None:
   old.blockSignals(True)
   if old.state()!=QProcess.NotRunning:old.kill()
   old.deleteLater()
  if not self.video:return
  cache_key=(self.video,round(float(position),3))
  cached=self.timeline_still_cache.get(cache_key)
  self.timeline_video_stack.setCurrentIndex(1)
  if cached is not None and not cached.isNull():
   self.timeline_current_original=cached
   self.timeline_still.setText('')
   self.timeline_still.setPixmap(cached.scaled(max(1,self.timeline_still.width()-8),max(1,self.timeline_still.height()-8),Qt.KeepAspectRatio,Qt.SmoothTransformation))
   return
  ffmpeg=tool('ffmpeg')
  if not ffmpeg:return
  self.timeline_current_original=None
  self.timeline_still.setText('Loading selected frame…')
  proc=QProcess(self);self.timeline_still_proc=proc
  proc.setProgram(ffmpeg)
  proc.setArguments(['-hide_banner','-loglevel','error','-nostdin','-ss',f'{position:.6f}', '-i',self.video,'-frames:v','1','-vf','scale=640:360:force_original_aspect_ratio=decrease','-f','image2pipe','-vcodec','png','-'])
  def done(code,status):
   if token!=self.timeline_still_token or proc is not self.timeline_still_proc:
    proc.deleteLater();return
   self.timeline_still_proc=None
   pix=QPixmap()
   if code==0:pix.loadFromData(bytes(proc.readAllStandardOutput()))
   if not pix.isNull():
    self.timeline_still_cache[cache_key]=pix
    if len(self.timeline_still_cache)>48:
     self.timeline_still_cache.pop(next(iter(self.timeline_still_cache)))
    self.timeline_current_original=pix
    self.timeline_still.setText('')
    self.timeline_still.setPixmap(pix.scaled(max(1,self.timeline_still.width()-8),max(1,self.timeline_still.height()-8),Qt.KeepAspectRatio,Qt.SmoothTransformation))
   else:self.timeline_still.setText('Current frame unavailable')
   proc.deleteLater()
  proc.finished.connect(done)
  proc.start()

 def timeline_inspector_media_ready(self,status):
  # A seek issued while the Timeline tab is loading its first video can be
  # ignored by the media backend. Retry once the media becomes seekable.
  if status in (QMediaPlayer.LoadedMedia,QMediaPlayer.BufferedMedia):
   target=self.timeline_pending_inspector_seek
   if target is not None and self.video:
    self.timeline_pending_inspector_seek=None
    self.timeline_player.setPosition(round(target*1000))

 def inspector_select_cut(self,row):
  if row<0 or row>=self.inspector_list.count():return
  index=self.inspector_list.item(row).data(Qt.UserRole)
  if index is None or not 0<=index<len(self.candidates):return
  c=self.candidates[index]
  state='Accepted' if c.get('keep') and not c.get('rejected') else ('Rejected' if c.get('rejected') else ('Recommended' if c.get('suggested') else 'Review Only'))
  self.inspector_detail.setText(f'{state} · {str(c.get("confidence","Unrated")).title()} confidence\n{c.get("reason") or c.get("source") or "No detection evidence recorded"}')
  if self.video:
   position=float(c['time'])
   # Initialize the Timeline's media source before seeking on first entry.
   if self.timeline_media_path!=self.video:self.timeline_refresh()
   self.timeline_pending_inspector_seek=position
   self.timeline_player.setPosition(round(position*1000))
   if self.timeline_player.mediaStatus() in (QMediaPlayer.LoadedMedia,QMediaPlayer.BufferedMedia):
    self.timeline_pending_inspector_seek=None
   self.timeline_request_split_preview(position)
   self.timeline_show_inspector_still(position)
   self.active_queue='scanned'
   for row in range(self.candidate_list.count()):
    if self.candidate_list.item(row).data(Qt.UserRole)==index:
     self.candidate_list.setCurrentRow(row)
     break

 def inspector_navigate(self,direction):
  count=self.inspector_list.count()
  if count:self.inspector_list.setCurrentRow(max(0,min(count-1,self.inspector_list.currentRow()+direction)))

 def inspector_decide(self,accept):
  item=self.inspector_list.currentItem()
  if item is None or not self.video or self.busy:return
  index=item.data(Qt.UserRole)
  if index is None or not 0<=index<len(self.candidates):return
  c=self.candidates[index]
  if bool(c.get('keep'))==bool(accept) and bool(c.get('rejected'))!=bool(accept):return
  self.timeline_snapshot()
  c['keep']=bool(accept);c['rejected']=not bool(accept);c.pop('suggested',None)
  self.sync_candidates(focus=index,queue='scanned')
  self.save_recovery()
  self.timeline_view.update()
  self.status.setText(('Accepted' if accept else 'Rejected')+f' cut at {fmt(float(c["time"]))}')

 def inspector_delete_selected_cut(self):
  """Remove an accepted split from the Inspector, synchronizing every editor."""
  if not self.video or self.busy:return
  item=self.inspector_list.currentItem()
  if item is None:return
  index=item.data(Qt.UserRole)
  if not isinstance(index,int) or not 0<=index<len(self.candidates):return
  candidate=self.candidates[index]
  if not (candidate.get('keep') and not candidate.get('rejected')):
   self.inspector_delete_review_candidate()
   return
  t=float(candidate['time'])
  if self.prefs.get('confirm_inspector_cut_delete',False):
   response=QMessageBox.question(self,'Remove accepted cut',
    f'Remove the accepted cut at {fmt(t)}?\n\n'
    'This merges the two neighboring clips and updates Review, Timeline and Export. '
    'You can restore the cut using Timeline Undo.',
    QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
   if response!=QMessageBox.Yes:return
  self.timeline_snapshot()
  # Reject all accepted candidates at this boundary so the split cannot survive
  # through a duplicate candidate from a previous scan.
  for c in self.candidates:
   if c.get('keep') and not c.get('rejected') and abs(float(c['time'])-t)<.002:
    c['keep']=False;c['rejected']=True;c.pop('suggested',None)
  self.timeline_view.selected=None
  self.active_queue='scanned'
  self.sync_candidates(focus=index,queue='scanned')
  self.save_recovery()
  self.refresh_selected_review_preview()
  self.status.setText(f'Removed accepted cut at {fmt(t)} — neighboring clips merged (Undo available)')
  if self.stack.currentIndex()==3:self.populate_gallery()

 def inspector_delete_review_candidate(self):
  if not self.video or self.busy:return
  item=self.inspector_list.currentItem()
  if item is None:return
  index=item.data(Qt.UserRole)
  if not isinstance(index,int) or not 0<=index<len(self.candidates):return
  if self.candidates[index].get('keep') and not self.candidates[index].get('rejected'):
   QMessageBox.information(self,'Accepted cut','This cut is accepted for export. Remove it from Accepted Cuts before deleting its review entry.')
   return
  t=float(self.candidates[index]['time'])
  self.timeline_snapshot()
  del self.candidates[index]
  remaining=[j for j in range(len(self.candidates))]
  self.active_queue='scanned';self.sync_candidates(focus=min(index,len(remaining)-1) if remaining else None,queue='scanned')
  self.refresh_selected_review_preview()
  self.save_recovery()
  self.timeline_view.update()
  self.status.setText(f'Deleted review suggestion at {fmt(t)}')
  if not self.inspector_list.count():self.timeline_request_split_preview()
 def timeline_review_tab_changed(self,index):
  if index==0 and self.video:self.timeline_refresh()
  if index==1 and self.video:
   self.sync_candidates()

 def go(self,index):
  # Existing buttons and keyboard shortcuts can still target old Review index 1.
  if index==1:
   index=2
   self.timeline_review_tabs.setCurrentIndex(1)
  elif index==2:
   self.timeline_review_tabs.setCurrentIndex(0)
  self.stack.setCurrentIndex(index)
  for page,button in self.nav:button.setChecked(page==index)
  if index==4:self.refresh_dashboard()
  if index==3:self.populate_gallery()
  if index==2 and self.timeline_review_tabs.currentIndex()==0:self.timeline_refresh()
 def read_interrupted_session(self):
  marker=APPDATA/'session_active.json'
  if not marker.is_file():return None
  try:
   data=json.loads(marker.read_text(encoding='utf-8'))
   if isinstance(data,dict) and isinstance(data.get('video'),str) and data['video']:
    return data
  except (OSError,ValueError,TypeError):pass
  return None
 def write_session_marker(self):
  try:
   APPDATA.mkdir(parents=True,exist_ok=True)
   marker=getattr(self,'session_marker',APPDATA/'session_active.json')
   tmp=marker.with_suffix('.tmp')
   tmp.write_text(json.dumps({'video':self.video,'project':self.project_path,'updated':time.time()}),encoding='utf-8')
   os.replace(tmp,marker)
  except OSError:pass
 def offer_interrupted_session_recovery(self):
  previous=self.previous_interrupted_session
  self.previous_interrupted_session=None
  if not previous or self.video:return
  video=previous.get('video','')
  if not Path(video).is_file():return
  recovery=self.find_video_recovery(video)
  if not recovery or not recovery.get('candidates'):return
  dialog=QMessageBox(self)
  dialog.setWindowTitle('Recover interrupted session')
  dialog.setText('Commercial Splitter may not have closed normally last time.')
  dialog.setInformativeText('Saved edits are available for '+Path(video).name+'. Restore them now?')
  restore=dialog.addButton('Restore Saved Cuts',QMessageBox.AcceptRole)
  dialog.addButton('Not Now',QMessageBox.RejectRole)
  dialog.setDefaultButton(restore)
  dialog.exec()
  if dialog.clickedButton() is restore:
   self.skip_next_video_recovery_prompt=True
   self.open_recovered_session_in_timeline=True
   self.load_video(video)
 def checkpoint_recovery(self,path):
  # Keep one previous version per recording, no unbounded accumulation.
  if not path.is_file():return
  now=time.monotonic()
  key=str(path)
  if now-self.recovery_checkpoint_at.get(key,0)<60:return
  try:
   previous=json.loads(path.read_text(encoding='utf-8'))
   if not isinstance(previous,dict):return
   backup=path.with_suffix('.checkpoint.json')
   tmp=backup.with_suffix('.tmp')
   tmp.write_text(json.dumps(previous,indent=2),encoding='utf-8')
   os.replace(tmp,backup)
   self.recovery_checkpoint_at[key]=now
  except (OSError,ValueError,TypeError):pass
 def project_signature(self):
  if not self.video or not self.duration:return None
  try:return json.dumps(self.project_snapshot(),sort_keys=True,ensure_ascii=False)
  except (ValueError,TypeError):return None
 def update_project_title(self):
  name=Path(self.project_path).name if self.project_path else (Path(self.video).name if self.video else 'Untitled')
  self.setWindowTitle('Commercial Splitter 4.9.0 — '+name+(' *' if self.project_dirty else ''))
 def autosave_tick(self):
  signature=self.project_signature()
  self.project_dirty=bool(signature is not None and signature!=self.saved_project_signature)
  self.update_project_title()
  if self.video:self.write_session_marker()
  if not self.project_dirty or not self.project_path or not self.prefs['autosave_enabled'] or self.busy:
   self.autosave_elapsed=0;return
  self.autosave_elapsed+=10
  if self.autosave_elapsed < self.prefs['autosave_minutes']*60:return
  self.autosave_elapsed=0
  # Use the same atomic write and backup path as manual Save Project.
  self.save_project(autosave=True)
 def confirm_discard_changes(self):
  if not self.video:return True
  self.project_dirty=self.project_signature()!=self.saved_project_signature
  if not self.project_dirty:return True
  result=QMessageBox.question(self,'Unsaved project changes','Save changes before closing this recording?',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Save)
  if result==QMessageBox.Cancel:return False
  if result==QMessageBox.Discard:return True
  self.save_project()
  return not self.project_dirty
 def closeEvent(self,event):
  if not self.confirm_discard_changes():event.ignore();return
  if self.busy:
   QMessageBox.information(self,'Operation in progress','Wait for the current operation to finish before exiting.')
   event.ignore();return
  # Save only on an accepted close, not when the user cancels exiting.
  try:
   import base64
   self.prefs['main_window_geometry']=base64.b64encode(bytes(self.saveGeometry())).decode('ascii')
   self.prefs['export_workspace_sizes']=self.export_workspace.sizes()
   self.save_preferences(self.prefs)
  except (OSError,ValueError,TypeError):pass
  try:self.session_marker.unlink(missing_ok=True)
  except OSError:pass
  event.accept()
 def project_snapshot(self):
  if not self.video or not self.duration:raise ValueError('Load a recording before saving a project.')
  return {'format':'CommercialSplitterProject','version':1,'video':self.video,
   'duration':self.duration,'fps':self.fps,'candidates':self.candidates,
   'clip_names':self.clip_names,'clip_order':self.normalized_clip_order(),
   'batch_excluded':sorted(self.batch_excluded),
   'export_folder':self.output_dir.text().strip(),
   'export_mode':self.export_mode.currentText()}
 def save_project(self,as_new=False,autosave=False):
  if self.busy:
   QMessageBox.information(self,'Busy','Wait until the current operation finishes.');return
  try:data=self.project_snapshot()
  except ValueError as e:QMessageBox.information(self,'Save Project',str(e));return
  path=self.project_path if not as_new else None
  if not path:
   if autosave:return
   suggested=str(Path(self.video).with_suffix('.csproj'))
   path,_=QFileDialog.getSaveFileName(self,'Save Commercial Splitter Project',suggested,'Commercial Splitter Projects (*.csproj)')
   if not path:return
  path=Path(path)
  if path.suffix.lower()!='.csproj':path=path.with_suffix('.csproj')
  # Relative media paths make the project portable when moved with its recording.
  try:data['video_relative']=os.path.relpath(self.video,path.parent)
  except ValueError:data['video_relative']=None
  try:
   path.parent.mkdir(parents=True,exist_ok=True)
   temp=path.with_name(path.name+'.tmp')
   temp.write_text(json.dumps(data,indent=2),encoding='utf-8')
   if path.is_file():shutil.copy2(path,path.with_name(path.name+'.bak'))
   os.replace(temp,path)
  except OSError as e:
   QMessageBox.warning(self,'Save failed',str(e));return
  self.project_path=str(path);self.autosave_elapsed=0;self.saved_project_signature=self.project_signature();self.project_dirty=False;self.update_project_title();self.add_recent_project(path)
  stamp=time.strftime('%Y-%m-%d %I:%M:%S %p')
  self.status.setText(f'{"Auto-saved" if autosave else "Project saved"} at {stamp}: {path.name}')
 def add_recent_project(self,path):
  path=str(Path(path).resolve())
  self.recent_projects=[path]+[x for x in self.recent_projects if x!=path]
  self.recent_projects=self.recent_projects[:10]
  self.prefs['recent_projects']=list(self.recent_projects)
  try:self.save_preferences(self.prefs)
  except OSError:pass
  self.refresh_recent_menu();self.refresh_dashboard()
 def refresh_recent_menu(self):
  self.recent_menu.clear()
  if not self.recent_projects:
   action=self.recent_menu.addAction('(No recent projects)');action.setEnabled(False);return
  for path in self.recent_projects[:10]:
   action=self.recent_menu.addAction(Path(path).name+'  —  '+str(Path(path).parent))
   action.setToolTip(path)
   action.triggered.connect(lambda checked=False,p=path:self.open_project_path(p))
 def reopen_last_project(self):
  if not self.recent_projects:
   self.status.setText('No recent projects to reopen');return
  self.open_project_path(self.recent_projects[0])
 def open_project(self):
  if self.busy:
   QMessageBox.information(self,'Busy','Wait until the current operation finishes.');return
  filename,_=QFileDialog.getOpenFileName(self,'Open Commercial Splitter Project',self.prefs.get('project_library_folder',str(ROOT)),'Commercial Splitter Projects (*.csproj);;All files (*)')
  if filename:self.open_project_path(filename)
 def open_project_path(self,filename):
  if self.busy:
   QMessageBox.information(self,'Busy','Wait until the current operation finishes.');return
  path=Path(filename).resolve()
  if not path.is_file():
   QMessageBox.warning(self,'Missing project',f'Project file not found:\n{path}\n\nYou can locate it and open it again using File → Open Project.')
   return
  try:
   data=json.loads(path.read_text(encoding='utf-8'))
   if not isinstance(data,dict) or data.get('format')!='CommercialSplitterProject' or data.get('version')!=1:
    raise ValueError('Unrecognized project format or version.')
   if not isinstance(data.get('candidates'),list) or not isinstance(data.get('clip_names'),dict):
    raise ValueError('Project data is incomplete.')
   media=[]
   if data.get('video_relative'):media.append((path.parent/str(data['video_relative'])).resolve())
   if data.get('video'):media.append(Path(str(data['video'])).resolve())
   video=next((x for x in media if x.is_file()),None)
   if video is None:
    candidate,_=QFileDialog.getOpenFileName(self,'Locate the source video for '+path.name,str(path.parent),VIDEO_FILTER)
    if not candidate:return
    video=Path(candidate).resolve()
    data['video']=str(video)
    # Use the located file for this session; preserve the project until explicitly saved.
  except (OSError,ValueError,TypeError) as e:
   QMessageBox.warning(self,'Open Project failed',str(e));return
  if self.video:
   self.close_project()
   if self.video:return
  self.pending_project=data
  self.load_video(str(video))
  if self.video==str(video):
   self.project_path=str(path)
   self.write_session_marker()
   self.add_recent_project(path)
  else:self.pending_project=None
 def restore_project_data(self,data):
  self.candidates=[]
  for entry in data['candidates']:
   if not isinstance(entry,dict):continue
   try:t=float(entry.get('time',-1))
   except (ValueError,TypeError):continue
   if math.isfinite(t) and 0<t<self.duration:
    clean=dict(entry);clean['time']=t;self.candidates.append(clean)
  self.candidates.sort(key=lambda x:float(x['time']))
  self.clip_names={str(k):v for k,v in data.get('clip_names',{}).items() if str(k).isdigit() and isinstance(v,str)}
  order=data.get('clip_order',[])
  excluded=data.get('batch_excluded',[])
  self.clip_order=[i for i in order if type(i) is int] if isinstance(order,list) else []
  self.batch_excluded={i for i in excluded if type(i) is int} if isinstance(excluded,list) else set()
  self.organizer_selected=set();self.organizer_anchor=None
  self.sync_candidates()
  self.clip_order=self.normalized_clip_order()
  if isinstance(data.get('export_folder'),str):self.output_dir.setText(data['export_folder'])
  if data.get('export_mode') in ('Accurate','Fast copy'):self.export_mode.setCurrentText(data['export_mode'])
  self.save_recovery()
  self.saved_project_signature=self.project_signature();self.project_dirty=False;self.update_project_title()
  self.status.setText('Project restored')
 def choose(self):
  path,_=QFileDialog.getOpenFileName(self,'Choose a recording',str(ROOT),VIDEO_FILTER)
  if path:self.load_video(path)
 def task(self,worker,callback):
  self.workers.append(worker)
  worker.ready.connect(callback)
  worker.finished.connect(lambda:self.workers.remove(worker) if worker in self.workers else None)
  worker.start()
 def close_project(self):
  if not self.video:return
  if not self.confirm_discard_changes():return
  if self.busy:
   if self.auto_process is not None:
    if QMessageBox.question(self,'Stop detection and close?','Stop automatic detection and close this project?')!=QMessageBox.Yes:return
    self.cancel_auto()
   elif self.scan_process and self.scan_process.state()!=QProcess.NotRunning:
    if QMessageBox.question(self,'Stop scan and close?','Scanning is in progress. Stop scanning and close this project?')!=QMessageBox.Yes:return
   else:
    QMessageBox.information(self,'Operation in progress','Wait for the current export to finish before closing the project.');return
  # Invalidate callbacks from the old recording before cancelling background processes.
  self.scan_token+=1;self.probe_id+=1;self.preview_generation+=1
  if self.scan_timer:self.scan_timer.stop()
  if self.probe_timer:self.probe_timer.stop()
  for process in [self.scan_process,self.probe_process,*self.frame_processes.values()]:
   if process is not None:
    process.blockSignals(True)
    if process.state()!=QProcess.NotRunning:process.kill()
    process.deleteLater()
  self.scan_process=None;self.probe_process=None;self.frame_processes={}
  self.timeline_cancel_split_preview();self.split_preview_cache.clear();self.review_frame_cache={}
  self.timeline_player.stop();self.timeline_player.setSource(QUrl());self.timeline_media_path=None;self.timeline_history.clear();self.timeline_future.clear();self.timeline_view.selected=None
  self.video=None;self.project_path=None;self.pending_project=None;self.saved_project_signature=None;self.project_dirty=False;self.duration=0;self.fps=30.0;self.cuts=[];self.candidates=[];self.clip_names={};self.clip_order=[];self.organizer_selected=set();self.organizer_anchor=None;self.batch_excluded=set();self.busy=False
  self.scan_times=[];self.scan_buffer='';self.scan_elapsed=0
  self.scan_btn.setEnabled(True);self.auto_btn.setEnabled(True);self.cancel_auto_btn.setEnabled(False);self.scan_progress.setValue(0);self.scan_detail.setText('Not scanning')
  self.candidate_list.blockSignals(True);self.candidate_list.clear();self.candidate_list.blockSignals(False)
  self.accepted_list.blockSignals(True);self.accepted_list.clear();self.accepted_list.blockSignals(False)
  self.active_queue='scanned';self.review_video.setText('Load a recording, then select a cut to compare its frames')
  for widget in (self.before_preview,self.after_preview):widget.clear();widget.setText('No preview')
  self.review_summary.setText('Load a recording to see saved accepted cuts.')
  self.info.setText('No recording loaded');self.import_file_path.setText('Drag a video into the area above, or browse to select a file.');self.update_import_visibility();self.status.setText('Project closed — choose another recording')
  self.output_dir.setText(self.default_export_root);self.progress.setValue(0)
  self.reset_export_preview();self.populate_gallery();self.show_dashboard()
  self.write_session_marker();self.update_project_title();log_load('PROJECT CLOSED')
 def update_import_visibility(self):
  loaded=bool(self.video)
  self.drop.setVisible(not loaded)
  self.import_scan_group.setVisible(loaded)

 def load_video(self,path):
  if self.video and str(Path(path).resolve())!=self.video:
   if self.busy:
    QMessageBox.information(self,'Operation in progress','Close the current project before opening a different recording.');return
   self.close_project()
   if self.video:return
  if not Path(path).is_file():
   QMessageBox.warning(self,'Missing video',str(path));return
  self.open_video_recovery_choice='keep'
  self.open_video_restored_cuts=False
  skip_recovery_prompt=getattr(self,'skip_next_video_recovery_prompt',False)
  self.skip_next_video_recovery_prompt=False
  if self.pending_project is None and not skip_recovery_prompt:
   # Look for existing autosaved cuts for this exact source video.
   recovery=self.find_video_recovery(path)
   if recovery and recovery.get('candidates'):
    prompt=QMessageBox(self)
    prompt.setWindowTitle('Previously edited recording')
    prompt.setText('Saved cuts were found for this video.')
    prompt.setInformativeText('Would you like to restore your previous cuts or start with an empty timeline?')
    keep=prompt.addButton('Keep Previous Cuts',QMessageBox.AcceptRole)
    fresh=prompt.addButton('Start Fresh',QMessageBox.DestructiveRole)
    prompt.addButton(QMessageBox.Cancel)
    prompt.setDefaultButton(keep)
    prompt.exec()
    if prompt.clickedButton() not in (keep,fresh):return
    if prompt.clickedButton() is fresh:self.open_video_recovery_choice='fresh'
    elif prompt.clickedButton() is keep:self.open_video_restored_cuts=True
  if self.pending_project is None:self.project_path=None
  self.saved_project_signature=None;self.project_dirty=False;self.autosave_elapsed=0
  self.probe_id+=1
  token=self.probe_id
  if self.probe_timer:self.probe_timer.stop()
  if self.probe_process and self.probe_process.state()!=QProcess.NotRunning:
   self.probe_process.blockSignals(True);self.probe_process.kill()
  self.timeline_clear_current_preview();self.timeline_still_cache.clear();self.timeline_stop_thumbnails();self.timeline_thumb_cache.clear();self.timeline_wave_cache.clear();self.timeline_zoom.setValue(0);self.timeline_pan.setValue(0);self.timeline_player.stop();self.timeline_media_path=None;self.timeline_player.setSource(QUrl());self.video=str(Path(path).resolve());self.output_dir.setText(self.project_export_folder());self.cuts=[];self.candidates=[];self.clip_names={};self.clip_order=[];self.organizer_selected=set();self.organizer_anchor=None;self.batch_excluded=set();self.duration=0;self.fps=30.0;self.preview_generation+=1
  self.before_preview.setText('Before cut\nNo preview');self.after_preview.setText('After cut\nNo preview')
  self.info.setText(Path(self.video).name)
  self.import_file_path.setText('Reading recording details…  •  '+self.video)
  self.update_import_visibility()
  self.status.setText('Reading video metadata…')
  self.go(0)  # Keep Import & Scan visible after choosing a recording.
  probe=tool('ffprobe')
  log_load(f'OPEN video={self.video!r} ffprobe={probe!r}')
  if not probe:
   self.probe_error('FFprobe was not found. Put ffprobe.exe in the tools folder or install FFmpeg.')
   return
  process=QProcess(self);self.probe_process=process
  process.setProgram(probe)
  process.setArguments(['-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',self.video])
  process.errorOccurred.connect(lambda error,t=token:self.on_probe_error(t,error))
  process.finished.connect(lambda code,status,t=token:self.on_probe_finished(t,code,status))
  timer=QTimer(self);timer.setSingleShot(True);self.probe_timer=timer
  timer.timeout.connect(lambda t=token:self.on_probe_timeout(t))
  timer.start(40000)
  process.start()
  log_load('Started Qt QProcess')
 def probe_error(self,message):
  log_load('ERROR: '+str(message))
  self.status.setText('Video loading failed')
  QMessageBox.warning(self,'Video loading error',str(message))
 def on_probe_error(self,token,error):
  if token!=self.probe_id:return
  log_load(f'QProcess error {error}: {self.probe_process.errorString()}')
  if self.probe_process.state()==QProcess.NotRunning:
   if self.probe_timer:self.probe_timer.stop()
   self.probe_error(self.probe_process.errorString())
 def on_probe_timeout(self,token):
  if token!=self.probe_id or self.duration:return
  log_load('TIMEOUT: ffprobe exceeded 40 seconds')
  if self.probe_process and self.probe_process.state()!=QProcess.NotRunning:
   self.probe_process.blockSignals(True);self.probe_process.kill()
  self.probe_error('FFprobe timed out after 40 seconds.')
 def on_probe_finished(self,token,code,status):
  if token!=self.probe_id or self.duration:return
  if self.probe_timer:self.probe_timer.stop()
  stdout=bytes(self.probe_process.readAllStandardOutput()).decode('utf-8','replace').strip()
  stderr=bytes(self.probe_process.readAllStandardError()).decode('utf-8','replace').strip()
  log_load(f'FINISHED code={code} stdout={stdout[:150]!r} stderr={stderr[:300]!r}')
  if code!=0:
   self.probe_error(stderr[-900:] or f'FFprobe exited with code {code}')
   return
  try:
   duration=float(stdout)
   if not (0<duration<1e9):raise ValueError('Invalid duration')
  except ValueError:
   self.probe_error(f'FFprobe returned an invalid duration: {stdout[:160]!r}')
   return
  self.duration=duration
  self.info.setText(f'{Path(self.video).name}   •   {fmt(duration)}')
  try:
   size_mb=Path(self.video).stat().st_size/(1024*1024)
   self.import_file_path.setText(f'{size_mb:,.1f} MB  •  {self.video}')
  except OSError:self.import_file_path.setText(self.video)
  self.status.setText('Metadata loaded — restoring saved cuts…')
  QTimer.singleShot(0,self.finish_video_load)
 def detect_frame_rate(self):
  # Read the video's actual nominal frame rate; retain a fallback for unusual streams.
  try:
   result=run([tool('ffprobe') or 'ffprobe','-v','error','-select_streams','v:0',
    '-show_entries','stream=avg_frame_rate','-of','default=noprint_wrappers=1:nokey=1',
    self.video],capture_output=True,text=True,timeout=15,check=True)
   from fractions import Fraction
   rate=float(Fraction(result.stdout.strip()))
   if 1<=rate<=240:self.fps=rate
  except (OSError,ValueError,ZeroDivisionError,subprocess.SubprocessError):
   log_load('Could not determine FPS; using 30 fps fallback')
 def finish_video_load(self):
  try:
   opened_project=self.pending_project is not None
   if opened_project:
    project=self.pending_project;self.pending_project=None
    self.restore_project_data(project)
   elif getattr(self,'open_video_recovery_choice','keep')=='fresh':
    self.candidates=[];self.cuts=[];self.clip_names={};self.clip_order=[];self.batch_excluded=set()
    self.sync_candidates()
    self.review_summary.setText('Started fresh. Previous cuts were not restored.')
    # Preserve the old recovery as a backup until new edits are saved.
    self.backup_video_recovery()
    self.save_recovery()
   else:self.read_recovery()
   recovered_session=getattr(self,'open_recovered_session_in_timeline',False)
   self.open_recovered_session_in_timeline=False
   if opened_project or recovered_session or getattr(self,'open_video_restored_cuts',False):
    # Navigate only after the asynchronous media probe and project restoration
    # finish; load_video() intentionally opens Import & Scan for plain videos.
    self.go(2)
   else:
    self.timeline_refresh()
   # Populate the new recording's paused preview immediately; don't wait for
   # the first user click, seek, or playback event to replace the old image.
   if self.video and self.duration and not self.timeline_player.isPlaying():
    self.timeline_show_inspector_still(self.timeline_player.position()/1000.)
   self.status.setText(f'Video restored in Timeline: {Path(self.video).name}' if recovered_session or getattr(self,'open_video_restored_cuts',False) else f'Project opened in Timeline: {Path(self.video).name}' if opened_project else f'Video ready: {Path(self.video).name}')
   log_load('SUCCESS: metadata and recovery loaded')
  except Exception:
   log_load('RECOVERY ERROR: '+traceback.format_exc())
   self.status.setText('Video loaded; recovery failed')
   QMessageBox.warning(self,'Recovery error','Video loaded, but saved cuts could not be restored.')
 def clear_video_recovery(self):
  if not self.video:return
  if self.busy:
   QMessageBox.information(self,'Operation in progress','Wait until the current operation finishes before clearing recovery.');return False
  if QMessageBox.question(self,'Start fresh?',
   'Clear all saved candidates, accepted cuts, and rejected decisions for this video?\n\n'
   'The original video and exported files will not be changed. This cannot be undone.',
   QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return False
  directory=APPDATA/'recovery'
  try:
   for path in directory.glob('*.json') if directory.exists() else []:
    try:
     data=json.loads(path.read_text(encoding='utf-8'))
     if Path(str(data.get('video',''))).resolve()==Path(self.video).resolve():path.unlink()
    except (ValueError,TypeError):continue
   self.candidates=[];self.cuts=[];self.preview_generation+=1
   self.sync_candidates();self.reset_export_preview();self.populate_gallery()
   self.status.setText('Recovery cleared — ready for a fresh scan')
   self.review_summary.setText('Recovery cleared. Scan recording to start fresh.')
   return True
  except OSError as exc:
   QMessageBox.warning(self,'Clear recovery failed',str(exc))
   return False
 def find_video_recovery(self,path):
  directory=APPDATA/'recovery'
  for p in directory.glob('*.json') if directory.exists() else []:
   try:
    data=json.loads(p.read_text(encoding='utf-8'))
    if Path(str(data.get('video',''))).resolve()==Path(path).resolve():
     return data
   except (OSError,ValueError,TypeError):pass
  return None
 def backup_video_recovery(self):
  original=self.recovery_file()
  if original.is_file():
   try:shutil.copy2(original,original.with_suffix('.previous.json.bak'))
   except OSError:pass

 def read_recovery(self):
  if not self.video:return
  directory=APPDATA/'recovery'
  # v3.x uses a different recovery hashing scheme; locate exact file through saved video path.
  found=None
  for p in directory.glob('*.json') if directory.exists() else []:
   try:
    data=json.loads(p.read_text(encoding='utf-8'))
    if Path(str(data.get('video',''))).resolve()==Path(self.video).resolve():found=data;break
   except (OSError,ValueError,TypeError):pass
  names=(found or {}).get('clip_names',{})
  if not isinstance(names,dict):names={}
  self.clip_names={str(k):v for k,v in names.items() if str(k).isdigit() and isinstance(v,str)}
  self.clip_order=(found or {}).get('clip_order',[]) if isinstance((found or {}).get('clip_order',[]),list) else []
  excluded=(found or {}).get('batch_excluded',[])
  self.batch_excluded={x for x in excluded if type(x) is int} if isinstance(excluded,list) else set()
  self.candidates=[]
  entries=(found or {}).get('candidates',[])
  if not isinstance(entries,list):entries=[]
  for entry in entries:
   if not isinstance(entry,dict):continue
   try:
    t=float(entry.get('time',0))
    if not math.isfinite(t) or not 0<t<self.duration:continue
   except (ValueError,TypeError,OverflowError):continue
   candidate=dict(entry);candidate['time']=t
   candidate.setdefault('rejected',False)
   self.candidates.append(candidate)
  self.candidates.sort(key=lambda c:c['time'])
  self.sync_candidates()
  if not found:self.review_summary.setText('No saved cuts found. Scan the recording to find candidates.')
  # Gallery is populated when Export is opened.
 def segments(self):
  bounds=[0.0]+self.cuts+[self.duration]
  return [(a,b) for a,b in zip(bounds,bounds[1:]) if b-a>.001]
 def export_change_view(self,mode):
  self.export_gallery_scroll.setVisible(mode=='Gallery')
  self.export_details.setVisible(mode=='Details')
  self.save_ui_preference('export_gallery_view',mode)
  if mode=='Details':self.export_details_select_current()

 def export_details_select_current(self):
  table=self.export_details
  for row in range(table.rowCount()):
   item=table.item(row,1)
   if item and item.data(Qt.UserRole)==getattr(self,'selected',-1):
    table.blockSignals(True)
    table.selectRow(row)
    table.blockSignals(False)
    return

 def export_details_selection_changed(self):
  table=self.export_details
  row=table.currentRow()
  if row<0:return
  item=table.item(row,1)
  if item is not None:
   index=item.data(Qt.UserRole)
   if index is not None and index!=getattr(self,'selected',None):self.select_card(index)

 def export_details_item_changed(self,item):
  if not self.video:return
  row=item.row();col=item.column()
  index_item=self.export_details.item(row,1)
  if index_item is None:return
  index=index_item.data(Qt.UserRole)
  if index is None:return
  if col==0:
   checked=item.checkState()==Qt.Checked
   name,include=self.export_names.get(index,(None,None))
   if include is not None and include.isChecked()!=checked:include.setChecked(checked)
   else:self.organizer_set_include(index,checked)
  elif col==5:
   name,include=self.export_names.get(index,(None,None))
   if name is not None:
    name.setText(item.text())
    self.export_name_changed(index,name)

 def export_populate_details(self,segs):
  table=self.export_details
  table.blockSignals(True)
  order=self.normalized_clip_order()
  table.setRowCount(len(order))
  for row,index in enumerate(order):
   a,b=segs[index]
   values=['',f'{index+1:03d}',fmt(a),fmt(b),fmt(b-a),self.clip_filename(index)]
   for col,value in enumerate(values):
    item=QTableWidgetItem(value)
    if col==1:item.setData(Qt.UserRole,index)
    if col==0:
     item.setFlags((item.flags()|Qt.ItemIsUserCheckable)&~Qt.ItemIsEditable)
     item.setCheckState(Qt.Unchecked if index in self.batch_excluded else Qt.Checked)
    elif col!=5:item.setFlags(item.flags()&~Qt.ItemIsEditable)
    if index in self.batch_excluded:item.setForeground(QColor('#aab5c1'))
    table.setItem(row,col,item)
  table.blockSignals(False)
  self.export_details_select_current()

 def export_sync_details_row(self,index):
  table=self.export_details
  for row in range(table.rowCount()):
   clip=table.item(row,1)
   if clip is not None and clip.data(Qt.UserRole)==index:
    table.blockSignals(True)
    check=table.item(row,0)
    if check:check.setCheckState(Qt.Unchecked if index in self.batch_excluded else Qt.Checked)
    filename=table.item(row,5)
    if filename:filename.setText(self.clip_filename(index))
    for col in range(table.columnCount()):
     item=table.item(row,col)
     if item:item.setForeground(QColor('#aab5c1') if index in self.batch_excluded else QColor('#e6eaf0'))
    table.blockSignals(False)
    break

 def populate_gallery(self):
  while self.gallery_layout.count():
   item=self.gallery_layout.takeAt(0)
   if item.widget():item.widget().deleteLater()
  previous_selection=getattr(self,'selected',0)
  self.cards=[];self.export_card_map={};self.selected=previous_selection;self.export_names={}
  if hasattr(self,'media_player'):self.media_player.pause()
  segs=self.segments() if self.video and self.duration else []
  self.export_desc.setText(f'{len(segs)} clips  •  {len(segs)-len(self.batch_excluded.intersection(set(range(len(segs)))))} included for export  •  Select a clip to preview its boundaries' if segs else 'No recording loaded')
  for display_pos,i in enumerate(self.normalized_clip_order()):
   a,b=segs[i]
   panel=QFrame();panel.setObjectName('clipPanel');cell=QVBoxLayout(panel)
   card=QPushButton(f'▶  Clip {i+1:03d}  •  {fmt(a)} – {fmt(b)}\n{b-a:.1f} sec')
   card.setObjectName('clipcard');card.setCheckable(True);card.setMinimumHeight(75);card.setChecked(i==previous_selection)
   card.clicked.connect(lambda _,idx=i:self.select_card(idx));cell.addWidget(card)
   name=QLineEdit(self.clip_filename(i));name.setPlaceholderText('Filename');name.editingFinished.connect(lambda idx=i,edit=name:self.export_name_changed(idx,edit));cell.addWidget(name)
   include=QCheckBox('Include in export');include.setChecked(i not in self.batch_excluded);include.toggled.connect(lambda checked,idx=i:self.organizer_set_include(idx,checked));cell.addWidget(include)
   self.gallery_layout.addWidget(panel,display_pos//3,display_pos%3);self.cards.append((i,card))
   self.export_names[i]=(name,include)
   self.export_card_map[i]=card
   self.export_style_card(i)
  self.export_populate_details(segs)
  if segs:
   self.select_card(previous_selection if 0<=previous_selection<len(segs) else self.normalized_clip_order()[0])
  else:
   self.export_selection_info.setText('No clips available')
   self.export_previous_clip.setEnabled(False);self.export_next_clip.setEnabled(False)
   self.reset_export_preview()
 def export_style_card(self,index):
  # Constant-time lookup keeps large galleries responsive.
  button=getattr(self,'export_card_map',{}).get(index)
  if button is None:return
  excluded=index in self.batch_excluded
  selected=index==getattr(self,'selected',-1)
  border='#66c7f4' if selected else ('#637080' if excluded else '#2d8d70')
  bg='#223a4c' if selected else ('#222832' if excluded else '#1c302d')
  fg='#aab5c1' if excluded else '#f0f5f8'
  button.setStyleSheet(
   f'QPushButton#clipcard {{background:{bg};color:{fg};border:2px solid {border};'
   'border-radius:7px;padding:8px;text-align:left;}'
   'QPushButton#clipcard:hover {border-color:#8acdf0;}')
  button.setToolTip('Excluded from export' if excluded else 'Included in export')

 def export_navigate(self,step):
  order=self.normalized_clip_order()
  if not order:return
  try:current=order.index(self.selected)
  except ValueError:current=0
  target=max(0,min(len(order)-1,current+step))
  self.select_card(order[target])

 def export_update_summary(self):
  if not self.video:return
  count=len(self.segments())
  included=sum(i not in self.batch_excluded for i in range(count))
  self.export_desc.setText(f'{count} clips  •  {included} included for export  •  Select a clip to preview its boundaries')
  if hasattr(self,'export_selection_info') and 0<=self.selected<count:
   order=self.normalized_clip_order()
   position=order.index(self.selected)+1 if self.selected in order else self.selected+1
   state='Included in export' if self.selected not in self.batch_excluded else 'Excluded from export'
   self.export_selection_info.setText(f'Clip {position} of {count} in export order  •  {state}')
   self.export_previous_clip.setEnabled(position>1)
   self.export_next_clip.setEnabled(position<count)

 def organizer_set_include(self,index,checked):
  if checked:self.batch_excluded.discard(index)
  else:self.batch_excluded.add(index)
  self.timeline_update_organizer_labels()
  self.export_update_summary()
  self.export_style_card(index)
  self.export_sync_details_row(index)
  self.save_recovery()
 def export_name_changed(self,index,edit):
  if not self.video:return
  raw=edit.text().strip()
  if raw.lower().endswith('.mp4'):raw=raw[:-4]
  if raw:self.clip_names[str(index)]=raw
  else:self.clip_names.pop(str(index),None)
  self.save_recovery()
  self.export_sync_details_row(index)
  self.timeline_update_clips()
 def select_card(self,index):
  previous=getattr(self,'selected',None)
  self.selected=index
  for i in (previous,index):
   if i is None:continue
   button=getattr(self,'export_card_map',{}).get(i)
   if button is not None:button.setChecked(i==index)
   self.export_style_card(i)
  self.export_update_summary()
  self.export_details_select_current()
  segs=self.segments()
  if not self.video or index>=len(segs):return
  a,b=segs[index]
  self.export_bounds=(round(a*1000),round(b*1000))
  self.media_player.pause()
  if self.export_media_path!=self.video:
   self.export_media_path=self.video
   self.media_player.setSource(QUrl.fromLocalFile(self.video))
  self.media_player.setPosition(self.export_bounds[0])
  self.export_seek.setValue(0)
  self.export_clock.setText(f'00:00 / {fmt(b-a)}')
  self.export_player_status.setText(f'Clip {index+1}: {fmt(a)} to {fmt(b)}. Play, pause, scrub, or skip within the clip.')
  self.update_export_still(a)
 def reset_export_preview(self):
  self.media_player.stop();self.media_player.setSource(QUrl())
  self.export_media_path=None;self.export_bounds=(0,0)
  self.export_seek.setValue(0);self.export_clock.setText('00:00 / 00:00')
  if self.export_still_process and self.export_still_process.state()!=QProcess.NotRunning:
   self.export_still_process.blockSignals(True);self.export_still_process.kill()
  self.export_still_process=None
  self.export_still.clear();self.export_still.setText('No clip selected')
  self.export_player_status.setText('Select a clip to preview.')
 def update_export_still(self,seconds):
  # The same clip can be revisited many times while reviewing a long recording.
  # Cache only 24 small JPEG previews, and include the video identity in the key.
  key=(self.video,round(seconds,3))
  cached=self.export_still_cache.get(key)
  if cached is not None:
   if self.export_still_process and self.export_still_process.state()!=QProcess.NotRunning:
    self.export_still_process.blockSignals(True);self.export_still_process.kill()
   self.export_still_process=None
   self.export_still.setPixmap(cached.scaled(300,190,Qt.KeepAspectRatio,Qt.SmoothTransformation))
   return
  if self.export_still_process:
   old=self.export_still_process
   old.blockSignals(True)
   if old.state()!=QProcess.NotRunning:old.kill()
   old.deleteLater()
  self.export_still.setText('Loading opening frame…')
  ff=tool('ffmpeg')
  if not ff:self.export_still.setText('FFmpeg unavailable');return
  process=QProcess(self);self.export_still_process=process
  process.setProgram(ff)
  process.setArguments(['-hide_banner','-loglevel','error','-nostdin','-i',self.video,'-ss',f'{seconds:.6f}','-map','0:v:0','-frames:v','1','-vf','scale=480:-2',
    '-f','image2pipe','-vcodec','mjpeg','-q:v','3','pipe:1'])
  def finished(code,status):
   if self.export_still_process is not process:return
   pix=QPixmap();data=bytes(process.readAllStandardOutput())
   if code==0 and pix.loadFromData(data):
    self.export_still_cache[key]=pix
    if len(self.export_still_cache)>24:
     self.export_still_cache.pop(next(iter(self.export_still_cache)))
    self.export_still.setPixmap(pix.scaled(300,190,Qt.KeepAspectRatio,Qt.SmoothTransformation))
   else:
    self.export_still.setText('Still image unavailable')
    log_load('EXPORT STILL: '+bytes(process.readAllStandardError()).decode('utf-8','replace')[-400:])
  process.finished.connect(finished)
  process.errorOccurred.connect(lambda err:self.export_still.setText('Still image process failed'))
  process.start()
 def toggle_export_play(self):
  if not self.video or not self.segments():
   QMessageBox.information(self,'No clip','Select a clip first.');return
  if self.media_player.isPlaying():self.media_player.pause();return
  start,end=self.export_bounds
  if self.media_player.position()<start or self.media_player.position()>=end-150:
   self.media_player.setPosition(start)
  self.media_player.play()
 def seek_export_slider(self,value):
  start,end=self.export_bounds
  if end>start:self.media_player.setPosition(start+round((end-start)*value/1000))
 def seek_export_relative(self,delta):
  start,end=self.export_bounds
  if end>start:self.media_player.setPosition(max(start,min(end-1,self.media_player.position()+delta)))
 def export_position_changed(self,position):
  start,end=self.export_bounds
  if end<=start:return
  if position>=end:
   self.media_player.pause();self.media_player.setPosition(max(start,end-1));position=end
  rel=max(0,min(end-start,position-start))
  if not self.export_seek.isSliderDown():self.export_seek.setValue(round(rel*1000/(end-start)))
  self.export_clock.setText(f'{fmt(rel/1000)} / {fmt((end-start)/1000)}')
 def export_media_status(self,status):
  if status==QMediaPlayer.EndOfMedia:
   self.media_player.pause()
   self.media_player.setPosition(self.export_bounds[0])
 def export_media_error(self,error,message):
  if error!=QMediaPlayer.NoError:
   self.export_player_status.setText('Playback error: '+message)
   log_load('EMBEDDED PLAYER: '+message)
 def export_playback_changed(self,state):
  self.export_play.setText('⏸ Pause' if state==QMediaPlayer.PlayingState else '▶ Play')
 def play_selected(self):
  segs=self.segments()
  if not self.video or not segs:return
  self.toggle_export_play()
 def recovery_file(self):
  digest=hashlib.sha256(os.path.normcase(str(Path(self.video).resolve())).encode('utf-8')).hexdigest()[:24]
  return APPDATA/'recovery'/(digest+'.json')
 def save_recovery(self):
  if not self.video:return
  path=self.recovery_file();path.parent.mkdir(parents=True,exist_ok=True)
  payload={'version':3,'recovery_version':1,'video':self.video,'duration':self.duration,'fps':self.fps,'candidates':self.candidates,'clip_names':self.clip_names,'clip_order':self.normalized_clip_order(),'batch_excluded':sorted(self.batch_excluded)}
  if path.exists():
   try:
    previous=json.loads(path.read_text(encoding='utf-8'))
    if isinstance(previous,dict):payload={**previous,**payload}
   except (OSError,ValueError):pass
  self.checkpoint_recovery(path)
  tmp=path.with_suffix('.tmp')
  try:
   tmp.write_text(json.dumps(payload,indent=2,allow_nan=False),encoding='utf-8')
   os.replace(tmp,path)
  except (OSError,ValueError,TypeError) as exc:
   log_load('RECOVERY SAVE FAILED: '+str(exc))
   try:tmp.unlink(missing_ok=True)
   except OSError:pass
 def candidate_index(self):
  listing=self.accepted_list if self.active_queue=='accepted' else self.candidate_list
  item=listing.currentItem()
  return item.data(Qt.UserRole) if item else -1
 def queue_selected(self,queue,row):
  if row<0:return
  self.active_queue=queue
  other=self.candidate_list if queue=='accepted' else self.accepted_list
  other.blockSignals(True);other.clearSelection();other.blockSignals(False)
  self.show_candidate(row)
 def sync_candidates(self,focus=None,queue=None):
  if focus is None:focus=self.candidate_index()
  target=queue or self.active_queue
  self.cuts=sorted(set(round(float(c['time']),3) for c in self.candidates if c.get('keep') and not c.get('rejected') and 0<float(c['time'])<self.duration))
  for listing in (self.candidate_list,self.accepted_list):listing.blockSignals(True);listing.clear()
  scanrow=acceptedrow=-1
  for i,c in enumerate(self.candidates):
   state='✓ Accepted' if c.get('keep') and not c.get('rejected') else ('× Rejected' if c.get('rejected') else ('★ Recommended' if c.get('suggested') else '○ Review Only'))
   tier=c.get('confidence')
   confidence=f'  •  [{tier.upper()} CONFIDENCE]' if tier else ''
   item=QListWidgetItem(f'{state}  •  {fmt(c["time"])}{confidence}  •  {c.get("source","Scene scan")}')
   if tier:item.setToolTip(f'{tier} confidence: {c.get("reason","No explanation available")}\n' + ('Recommended by current detection run' if c.get('suggested') else 'Review Only — not recommended by current detection run'))
   # Consistent status coloring in both themes, without changing cut state.
   light=self.prefs.get('theme')=='light'
   accepted_cut=bool(c.get('keep') and not c.get('rejected'))
   manual_cut=str(tier).lower()=='manual' or str(c.get('source','')).lower().startswith('timeline manual')
   if c.get('rejected'):color='#a7b0bb' if not light else '#545c65'
   elif accepted_cut and manual_cut:color='#82bfff' if not light else '#a9d4ff'
   elif accepted_cut and str(tier).lower()=='low':color='#d6bcff' if not light else '#d5b8fa'
   elif accepted_cut:color='#58d6b3' if not light else '#9de4ca'
   elif c.get('suggested'):color='#f1c477' if not light else '#f0d39b'
   else:color='#c6ced8' if not light else '#e1e5eb'
   item.setForeground(QBrush(QColor(color)))
   item.setData(Qt.UserRole,i);self.candidate_list.addItem(item)
   if i==focus:scanrow=self.candidate_list.count()-1
   if c.get('keep') and not c.get('rejected'):
    accepted=QListWidgetItem(f'✓  {fmt(c["time"])}' + (f'  •  [{tier.upper()}]' if tier else ''));accepted.setData(Qt.UserRole,i)
    accepted.setForeground(QBrush(QColor(color)))
    if tier:accepted.setToolTip(c.get('reason',''))
    self.accepted_list.addItem(accepted)
    if i==focus:acceptedrow=self.accepted_list.count()-1
  for listing in (self.candidate_list,self.accepted_list):listing.blockSignals(False)
  if target=='accepted' and acceptedrow>=0:
   self.active_queue='accepted';self.accepted_list.setCurrentRow(acceptedrow)
  elif self.candidate_list.count():
   self.active_queue='scanned';self.candidate_list.setCurrentRow(max(0,scanrow))
  else:
   self.preview_generation+=1;self.review_video.setText('No scanned scenes yet')
   self.before_preview.clear();self.before_preview.setText('No preview')
   self.after_preview.clear();self.after_preview.setText('No preview')
  rejected=sum(bool(c.get('rejected')) for c in self.candidates)
  pending=sum(not c.get('keep') and not c.get('rejected') for c in self.candidates)
  if hasattr(self,'timeline_view'):
   self.timeline_view.update();self.timeline_update_clips();self.timeline_selection_changed()
  self.review_summary.setText(f'{len(self.cuts)} accepted  •  {pending} pending  •  {rejected} rejected (still visible)  •  {len(self.cuts)+1} segments')
  self.update_detection_feedback()
  self.inspector_refresh(focus) if hasattr(self,'inspector_list') else None
 def request_preview(self,widget,seconds,generation):
  if not hasattr(self,'review_frame_cache'):self.review_frame_cache={}
  key=(self.video,round(float(seconds),4))
  if key in self.review_frame_cache:
   pix=self.review_frame_cache[key]
   widget.setPixmap(pix.scaled(480,270,Qt.KeepAspectRatio,Qt.SmoothTransformation))
   return
  ff=tool('ffmpeg')
  if not ff:widget.setText('FFmpeg missing');return
  old=self.frame_processes.pop(widget,None)
  if old and old.state()!=QProcess.NotRunning:old.blockSignals(True);old.kill()
  proc=QProcess(self);self.frame_processes[widget]=proc
  proc.setProgram(ff)
  proc.setArguments(['-hide_banner','-loglevel','error','-nostdin','-ss',f'{seconds:.6f}','-accurate_seek','-i',self.video,'-map','0:v:0','-frames:v','1','-vf','scale=480:-2','-f','image2pipe','-vcodec','mjpeg','-q:v','3','pipe:1'])
  def finished(code,status):
   if self.frame_processes.get(widget) is not proc or generation!=self.preview_generation:
    proc.deleteLater();return
   self.frame_processes.pop(widget,None)
   data=bytes(proc.readAllStandardOutput());pix=QPixmap()
   if code==0 and pix.loadFromData(data):
    self.review_frame_cache[key]=pix
    if len(self.review_frame_cache)>90:self.review_frame_cache.pop(next(iter(self.review_frame_cache)))
    widget.setPixmap(pix.scaled(480,270,Qt.KeepAspectRatio,Qt.SmoothTransformation))
   else:
    log_load('Preview failure: '+bytes(proc.readAllStandardError()).decode('utf-8','replace')[-400:]);widget.setText('Preview unavailable')
   proc.deleteLater()
  proc.finished.connect(finished)
  proc.errorOccurred.connect(lambda err:log_load('Preview process: '+proc.errorString()))
  proc.start()
  QTimer.singleShot(20000,lambda p=proc,w=widget,g=generation:self.frame_timeout(p,w,g))
 def frame_timeout(self,proc,widget,generation):
  if generation!=self.preview_generation or self.frame_processes.get(widget) is not proc:return
  if proc.state()!=QProcess.NotRunning:
   proc.blockSignals(True);proc.kill();widget.setText('Preview timed out');log_load('Preview timed out')
 def scan_native(self):
  """One-pass scan: collect scene, black and silence evidence and suggest cuts."""
  if not self.video or self.busy or not self.duration:return
  # Auto Suggest Cuts already scans all three signals in a single FFmpeg pass.
  # Do not run the older scene-only pass first: it duplicates the video decode
  # and can introduce preliminary scene candidates that are later discarded.
  self.auto_suggest()

 def scan_process_error(self,token,error):
  if token!=self.scan_token:return
  log_load('Scan process: '+self.scan_process.errorString())
  if self.scan_process.state()==QProcess.NotRunning:
   if self.scan_timer:self.scan_timer.stop()
   self.busy=False;self.scan_btn.setEnabled(True)
   self.status.setText('Scan could not start')
   QMessageBox.warning(self,'Scan error',self.scan_process.errorString())
 def scan_read_output(self,token=None):
  if token is not None and token!=self.scan_token:return
  if not self.scan_process:return
  self.scan_buffer+=bytes(self.scan_process.readAllStandardError()).decode('utf-8','replace')
  lines=self.scan_buffer.split('\n');self.scan_buffer=lines.pop()
  for line in lines:
   if 'showinfo' in line:
    match=re.search(r'pts_time:\s*([0-9.]+)',line)
    if match:
     t=float(match.group(1))
     if t>0 and (not self.scan_times or t-self.scan_times[-1]>=self.gap.value()):self.scan_times.append(t)
   # out_time is the decoded input timestamp. With select filter it can stall
   # between detections, so also use FFmpeg's time= stats if available.
   match=re.search(r'^out_time=(\d+):(\d+):(\d+(?:\.\d+)?)',line.strip())
   if match:
    h,m,sec=match.groups();self.scan_elapsed=max(self.scan_elapsed,int(h)*3600+int(m)*60+float(sec))
   match=re.search(r'time=(\d+):(\d+):(\d+(?:\.\d+)?)',line)
   if match:
    h,m,sec=match.groups();self.scan_elapsed=max(self.scan_elapsed,int(h)*3600+int(m)*60+float(sec))
  self.scan_status_update(token)
 def scan_status_update(self,token=None):
  if token is not None and token!=self.scan_token:return
  if not self.busy or not self.video:return
  percent=min(99,round(self.scan_elapsed/max(.001,self.duration)*100))
  self.scan_progress.setValue(percent)
  self.scan_detail.setText(f'{fmt(self.scan_elapsed)} / {fmt(self.duration)} • {len(self.scan_times)} scenes')
  self.status.setText(f'Scanning… {percent}% • {len(self.scan_times)} candidates detected')
 def scan_finished(self,code,status,token=None):
  if token is not None and token!=self.scan_token:return
  self.scan_read_output(token)
  if self.scan_timer:self.scan_timer.stop()
  self.busy=False;self.scan_btn.setEnabled(True);self.auto_btn.setEnabled(True)
  log_load(f'Scan exit={code}, candidates={len(self.scan_times)}')
  if code!=0:
   self.status.setText('Scan failed');self.scan_detail.setText('Scan failed')
   QMessageBox.warning(self,'Scan error',f'FFmpeg exited with code {code}. See diagnostics log.');return
  previous={round(float(c['time']),3):dict(c) for c in self.candidates}
  self.candidates=[dict(previous.get(round(t,3),{'time':t,'keep':False,'rejected':False,'source':'Scene scan'})) for t in self.scan_times]
  for key,old in previous.items():
   if old.get('keep') and not old.get('rejected') and not any(abs(float(c['time'])-key)<.001 for c in self.candidates):self.candidates.append(old)
  self.candidates.sort(key=lambda c:float(c['time']))
  self.sync_candidates();self.save_recovery()
  self.scan_progress.setValue(100);self.scan_detail.setText(f'{fmt(self.duration)} / {fmt(self.duration)} • {len(self.scan_times)} scenes')
  self.status.setText(f'Scan complete: {len(self.scan_times)} candidates')
 def cancel_auto(self):
  self.auto_token+=1
  if self.auto_timer:self.auto_timer.stop();self.auto_timer.deleteLater();self.auto_timer=None
  proc=self.auto_process;self.auto_process=None
  if proc is not None:
   proc.blockSignals(True)
   if proc.state()!=QProcess.NotRunning:proc.kill()
   proc.deleteLater()
  self.busy=False;self.auto_btn.setEnabled(True);self.scan_btn.setEnabled(True);self.cancel_auto_btn.setEnabled(False)
  self.auto_progress.setFormat('Cancelled at %p%');self.auto_progress_detail.setText('Automatic detection cancelled')
  self.status.setText('Automatic detection cancelled')
 def inspect_detected_boundary(self):
  if not self.video:
   QMessageBox.information(self,'Inspect boundary','Import a recording first.');return
  stamp,ok=QInputDialog.getText(self,'Inspect Detected Boundary','Timestamp (MM:SS or HH:MM:SS):',text='02:17')
  if not ok:return
  try:
   parts=[float(v) for v in stamp.strip().split(':')]
   if not parts or len(parts)>3:raise ValueError
   target=sum(v*60**i for i,v in enumerate(reversed(parts)))
   if target<0 or target>self.duration:raise ValueError
  except ValueError:
   QMessageBox.warning(self,'Invalid timestamp','Enter a time such as 02:17 or 00:02:17.');return
  black=sorted((a,b) for a,b,_ in getattr(self,'auto_black_intervals',[]) if a-4<=target<=b+4)
  visual=sorted(t for t in getattr(self,'auto_visual_times',[]) if abs(t-target)<=4)
  suggestions=sorted((float(c['time']),c) for c in self.candidates if abs(float(c['time'])-target)<=4)
  lines=[f'Target: {fmt(target)}',f'Raw black intervals (within 4s): {len(black)}']
  lines.extend(f'  {fmt(a)} to {fmt(b)}' for a,b in black)
  lines.append(f'Raw scene transitions (within 4s): {len(visual)}')
  lines.extend(f'  {fmt(t)}' for t in visual[:20])
  lines.append(f'Review candidates (within 4s): {len(suggestions)}')
  for t,c in suggestions:
   state='Accepted' if c.get('keep') else 'Rejected' if c.get('rejected') else 'Suggested' if c.get('suggested') else 'Review only'
   lines.append(f'  {fmt(t)} — {state}: {c.get("reason",c.get("source",""))}')
  if not getattr(self,'auto_black_intervals',None):lines.append('No raw black intervals saved; run Auto Suggest Cuts first.')
  QMessageBox.information(self,'Boundary detection diagnostics','\n'.join(lines))

 def detection_candidates_for_mode(self,mode):
  """Combine visual, black-frame, and silence evidence into review suggestions."""
  black=[(float(a),float(b),float(length)) for a,b,length in sorted(self.auto_black_intervals)
         if length>=.04 and 1<float(a)<self.duration-1]
  visual=sorted(float(t) for t in self.auto_visual_times if 1<float(t)<self.duration-1)
  silence=sorted((float(a),float(b),float(length)) for a,b,length in self.auto_silence_intervals
                 if length>=.12)
  evidence=sorted([(t,'black',length) for t,end,length in black]+
                  [(t,'visual',0.) for t in visual])
  clusters=[]
  for item in evidence:
   # Compare to the first point, not the last, to avoid chaining several
   # unrelated scene changes into one large transition.
   if clusters and item[0]-clusters[-1][0][0]<=.45:clusters[-1].append(item)
   else:clusters.append([item])
  scored=[]
  for cluster in clusters:
   blacks=[x for x in cluster if x[1]=='black']
   scenes=[x for x in cluster if x[1]=='visual']
   black_match=bool(blacks);scene_match=bool(scenes)
   anchor=min(x[0] for x in blacks) if black_match else min(x[0] for x in scenes)
   initial=anchor
   # Prefer an audio endpoint only if it is genuinely adjacent to the
   # visual transition. Scene-only boundaries need this too, not just black.
   # A silence beginning well after the picture change may belong to the
   # next segment, so cap the adjustment at 1.2 seconds.
   # Black-screen transitions may precede the end of the outgoing audio,
   # so move those cuts to nearby silence as before. For direct scene
   # changes, silence after the scene often belongs to the new commercial:
   # moving the cut there makes it late and clips the new commercial's start.
   if black_match:
    # Cut when outgoing audio first settles into sustained silence INSIDE
    # the black interval. Do not cut at black_start while audio is playing.
    black_end=min((end for start,end,length in black
                   if abs(start-initial)<.05),default=initial)
    eligible=[a for a,b,length in silence
              if initial-.03<=a<=black_end-.01 and
              min(b,black_end)-max(a,initial)>=.12]
    if eligible:anchor=max(initial,min(eligible))
    # If no reliable silence was detected, retain a review candidate at
    # the visual boundary; don't pretend its audio is clean.
   audio_adjusted=anchor>initial+.025
   # Silence that ends immediately before a scene change is also supporting
   # evidence, but must not pull the cut backwards into the preceding clip.
   silence_match=any(a-.55<=initial<=b+.55 or abs(a-anchor)<=.20
                     for a,b,length in silence)
   score=(2 if black_match else 0)+(2 if scene_match else 0)+(1 if silence_match else 0)
   tier='High' if score>=4 else 'Medium' if score>=2 else 'Low'
   # Digital Recordings can have a clean hard scene change without a
   # black interval or detectable silence. Retain these for manual review.
   digital_scene_only=(self.profile_picker.currentText()=='Digital Recordings'
                       and scene_match and not black_match and score==2)
   if mode=='Conservative' and score<3 and not digital_scene_only:continue
   if digital_scene_only:
    tier='Low'
    reason_hint='; digital scene-only candidate — review start boundary'
   else:reason_hint=''
   if mode=='Balanced' and score<2:continue
   reason='Black transition' if black_match else 'Scene transition (no black required)'
   if black_match and scene_match:reason+=' with scene change'
   if silence_match:reason+=' and nearby silence'
   if scene_match and not black_match:reason+='; anchored to visual start'
   if audio_adjusted:reason+='; moved to sustained silence inside black interval'
   elif black_match:reason+='; audio end unconfirmed — review'
   scored.append((anchor,score,tier,reason+reason_hint))
  # Recover raw black intervals not represented by a scored cluster.
  # Use the same audio-aware placement as the primary pass. Never add an
  # additional raw-start cut that could split the outgoing audio.
  for black_start,black_end,black_length in black:
   if any(row[3].startswith('Black transition') and
          black_start-.03<=row[0]<=black_end+.03 for row in scored):
    continue
   eligible=[a for a,b,length in silence
             if black_start-.03<=a<=black_end-.01 and
             min(b,black_end)-max(a,black_start)>=.12]
   position=max(black_start,min(eligible)) if eligible else black_start
   note=('audio ends during black interval' if eligible
         else 'audio end unconfirmed — review before accepting')
   scored.append((position,2,'Low',f'Black transition (recovered; {note})'))
  accepted=sorted(float(c['time']) for c in self.candidates if c.get('keep'))
  minimum=float(self.detection_min.value());maximum=max(minimum,float(self.detection_max.value()))
  # When a strong black transition follows a scene-only candidate by a few
  # seconds, the scene candidate can be a false early boundary. Prefer the
  # audio-aligned black transition while leaving all other scenes untouched.
  black_positions=[t for t,score,tier,reason in scored
                   if reason.startswith('Black transition') and
                   'moved to sustained silence' in reason]
  scored=[row for row in scored
          if row[3].startswith('Black transition') or
          not any(0 < black_t-row[0] <= 3.0 for black_t in black_positions)]
  # Prioritize real black intervals before competing scene-only suggestions.
  # A nearby high-scoring scene must not suppress a distinct black-screen start.
  ranked=sorted(scored,key=lambda row:(0 if row[3].startswith('Black transition') else 1,-row[1],row[0]))
  chosen=[]
  for t,score,tier,reason in ranked:
   is_black=reason.startswith('Black transition')
   # The minimum segment duration is a ranking heuristic, not a reason to
   # hide a real black interval from review. Keep near-edge black candidates.
   if (t<minimum or self.duration-t<minimum) and not is_black:continue
   if (t<minimum or self.duration-t<minimum) and is_black:
    tier='Low';reason+='; near recording edge — review manually' 
   # A black transition can be a genuine commercial start even when
   # it is closer to an accepted cut than the minimum clip duration.
   # Keep it for review unless it is effectively the same boundary.
   accepted_distance=min((abs(t-a) for a in accepted),default=float('inf'))
   if accepted_distance<(0.08 if is_black else max(.25,minimum)):continue
   if is_black and accepted_distance<minimum:
    tier='Low';reason+='; near accepted cut — review black-screen start'
   # Scene-only boundaries may be closer than typical commercial spacing.
   # Keep them as lower-confidence review suggestions instead of discarding.
   nearest=min((abs(t-other[0]) for other in chosen),default=float('inf'))
   if nearest<minimum:
    if score<2 or nearest<(0.035 if is_black else max(1.0,minimum*.35)):continue
    tier='Low';reason+='; closely spaced candidate — review manually'

   chosen.append((t,score,tier,reason))
  chosen.sort(key=lambda row:row[0])
  result=[];previous=0.
  for t,score,tier,reason in chosen:
   if t-previous>maximum:reason+='; preceding span exceeds maximum (review)'
   result.append((round(t,3),tier,reason));previous=t
  return result
 def compare_detection_modes(self):
  if not self.video or not getattr(self,'auto_visual_times',None) and not getattr(self,'auto_black_intervals',None):
   QMessageBox.information(self,'Compare modes','Run Auto Suggest Cuts once to collect transition evidence, then compare modes.');return
  lines=[]
  for mode in ('Conservative','Balanced','Aggressive'):
   results=self.detection_candidates_for_mode(mode)
   lines.append(f'{mode}: {len(results)} suggested boundaries ('+ ', '.join(f'{tier}: {sum(level==tier for _,level,_ in results)}' for tier in ('High','Medium','Low'))+')')
  QMessageBox.information(self,'Smart Detection v3 — comparison','\n'.join(lines)+'\n\nComparison does not change existing cuts. Choose a mode and run Auto Suggest Cuts to apply its suggestions.')
 def auto_suggest(self):
  if not self.video or self.busy or not self.duration:return
  ff=tool('ffmpeg')
  if not ff:QMessageBox.warning(self,'FFmpeg missing','FFmpeg was not found.');return
  self.busy=True;self.auto_token+=1;token=self.auto_token
  self.auto_btn.setEnabled(False);self.scan_btn.setEnabled(False);self.cancel_auto_btn.setEnabled(True)
  self.auto_progress.setRange(0,100);self.auto_progress.setValue(0);self.auto_progress.setFormat('%p% analyzed');self.auto_progress.setVisible(True)
  self.auto_progress_detail.setText(f'{fmt(0)} / {fmt(self.duration)} • analyzing transitions');self.auto_progress_detail.setVisible(True)
  self.status.setText('Scanning video and suggesting cuts in one pass… (Cancel to stop)')
  self.auto_buffer='';self.auto_black_intervals=[];self.auto_black_start=None;self.auto_visual_times=[];self.auto_silence_intervals=[];self.auto_silence_start=None
  proc=QProcess(self);self.auto_process=proc
  proc.setProgram(ff)
  # Detect >= 40 ms mostly-black intervals; review short black transitions manually.
  # Analysis uses a separate FFmpeg process so the Qt interface remains responsive.
  proc.setArguments(['-hide_banner','-nostdin','-nostats','-stats_period','0.5','-progress','pipe:2','-i',self.video,'-vf',
   f'blackdetect=d=0.04:pix_th={getattr(self,"active_black_threshold",.12):.3f}:pic_th=0.95,select=gt(scene\\,{min(.40,self.threshold.value()):.3f}),showinfo',
   '-af',f'silencedetect=noise={getattr(self,"active_silence_db",-32)}dB:d=0.06','-f','null','-'])
  proc.readyReadStandardError.connect(lambda t=token:self.auto_read(t))
  proc.finished.connect(lambda code,status,t=token:self.auto_finished(t,code))
  proc.errorOccurred.connect(lambda err,t=token:self.auto_error(t))
  timer=QTimer(self);timer.setSingleShot(True);self.auto_timer=timer
  timer.timeout.connect(lambda t=token:self.auto_timeout(t));timer.start(300000)
  proc.start()
 def auto_read(self,token):
  if token!=self.auto_token or self.auto_process is None:return
  self.auto_buffer+=bytes(self.auto_process.readAllStandardError()).decode('utf-8','replace')
  lines=re.split(r'[\r\n]+',self.auto_buffer);self.auto_buffer=lines.pop()
  for line in lines:
   # FFmpeg -progress reports processed media time, independent of detected cuts.
   progress_time=re.match(r'^out_time=(\d+):(\d+):(\d+(?:\.\d+)?)$',line.strip())
   if progress_time:
    hours,minutes,seconds=progress_time.groups()
    elapsed=int(hours)*3600+int(minutes)*60+float(seconds)
    elapsed=max(0.,min(self.duration,elapsed))
    percent=min(99,int(elapsed/self.duration*100)) if self.duration>0 else 0
    if percent>self.auto_progress.value():self.auto_progress.setValue(percent)
    self.auto_progress_detail.setText(f'{fmt(elapsed)} / {fmt(self.duration)} • analyzing transitions')
   match=re.search(r'black_start:\s*([0-9.]+)\s+black_end:\s*([0-9.]+)\s+black_duration:\s*([0-9.]+)',line)
   if match:self.auto_black_intervals.append(tuple(map(float,match.groups())))
   if 'showinfo' in line:
    visual=re.search(r'pts_time:\s*([0-9.]+)',line)
    if visual:self.auto_visual_times.append(float(visual.group(1)))
   start=re.search(r'silence_start:\s*([0-9.]+)',line)
   if start:self.auto_silence_start=float(start.group(1))
   end=re.search(r'silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)',line)
   if end:
    stop,length=map(float,end.groups())
    self.auto_silence_intervals.append((stop-length,stop,length))
    self.auto_silence_start=None
 def auto_error(self,token):
  if token!=self.auto_token or self.auto_process is None:return
  if self.auto_process.state()==QProcess.NotRunning:
   message=self.auto_process.errorString();self.cancel_auto()
   QMessageBox.warning(self,'Detection error',message)
 def auto_timeout(self,token):
  if token!=self.auto_token:return
  self.cancel_auto()
  QMessageBox.warning(self,'Detection timed out','Detection exceeded 5 minutes and was stopped. Try a shorter recording.')
 def auto_finished(self,token,code):
  if token!=self.auto_token or self.auto_process is None:return
  self.auto_read(token)
  # FFmpeg may omit a final newline.
  tail=self.auto_buffer
  match=re.search(r'black_start:\s*([0-9.]+)\s+black_end:\s*([0-9.]+)\s+black_duration:\s*([0-9.]+)',tail)
  if match:self.auto_black_intervals.append(tuple(map(float,match.groups())))
  proc=self.auto_process
  if self.auto_timer:self.auto_timer.stop();self.auto_timer.deleteLater();self.auto_timer=None
  self.auto_process=None;proc.deleteLater()
  self.busy=False;self.auto_btn.setEnabled(True);self.scan_btn.setEnabled(True);self.cancel_auto_btn.setEnabled(False)
  if code!=0:
   self.auto_progress.setFormat('Detection failed at %p%');self.auto_progress_detail.setText('Automatic detection failed')
   self.status.setText('Transition detection failed')
   QMessageBox.warning(self,'Detection error',f'FFmpeg exited with code {code}.');return
  self.auto_progress.setValue(100);self.auto_progress.setFormat('Analysis complete — 100%')
  self.auto_progress_detail.setText(f'{fmt(self.duration)} / {fmt(self.duration)} • analysis complete')
  # Rebuild *undecided* automatic suggestions from the current scan.
  # Previous runs used to leave stale review-only scene cuts behind.
  self.candidates=[c for c in self.candidates
    if c.get('keep') or c.get('rejected') or
       'manual' in str(c.get('source','')).lower()]
  results=self.detection_candidates_for_mode(self.detection_sensitivity.currentText())
  # A black interval is stronger evidence of a commercial boundary than a
  # scene-only change a few seconds before it. Preserve the audio-aligned
  # black boundary even if candidate ranking/spacing removed it.
  black_recovery=[]
  for start,end,length in sorted(self.auto_black_intervals):
   if length<.12 or not (1<start<self.duration-1):continue
   quiet=[a for a,b,d in self.auto_silence_intervals
          if start-.03<=a<end and min(b,end)-max(a,start)>=.12]
   if not quiet:continue
   position=round(max(start,min(quiet)),3)
   black_recovery.append((position,'Low',
      f'Black interval {start:.3f}–{end:.3f}; silence begins {position:.3f}'))
  for position,tier,reason in black_recovery:
   if not any(abs(t-position)<.12 and r.startswith('Black transition')
              for t,level,r in results):
    results.append((position,tier,'Black transition; '+reason))
  # Drop a scene-only cut preceding a nearby audio-aligned black boundary.
  # This directly prevents 02:14.608 winning over the 02:16.9 boundary.
  black_positions=[t for t,level,reason in results if reason.startswith('Black transition')]
  results=[(t,level,reason) for t,level,reason in results
    if reason.startswith('Black transition') or
       not any(0<bt-t<=3.0 for bt in black_positions)]
  results.sort(key=lambda row:row[0])
  added=high=medium=low=0
  for t,tier,reason in results:
   near=next((c for c in self.candidates if abs(float(c['time'])-t)<.15),None)
   if near is None:
    near={'time':round(t,3),'keep':False,'rejected':False,
          'source':'Smart Detection v3'}
    self.candidates.append(near);added+=1
   if near.get('keep') or near.get('rejected'):continue
   near['confidence']=tier;near['reason']=reason;near['suggested']=True
   if tier in ('High','Medium'):
    near['keep']=True
    near['rejected']=False
    near['suggested']=False
   if tier=='High':high+=1
   elif tier=='Medium':medium+=1
   else:low+=1
  self.candidates.sort(key=lambda c:float(c['time']))
  self.sync_candidates();self.save_recovery()
  self.status.setText(f'{high} high, {medium} medium suggestions; {low} visual-only candidates')
  QMessageBox.information(self,'Smart Detection v3',
   f'{high} high-confidence suggestions\n{medium} medium-confidence suggestions\n'
   f'{low} low-confidence suggestions\n\n'
   f'{added} new detection candidates added. Medium/High cuts were automatically placed.\n\n'
   'Low-confidence suggestions remain available in Review Suggested Cuts.\n\n'
   'Heuristic confidence is not a probability. Review all boundaries. '
   'Please verify all boundaries before exporting.')
 def detection_feedback_stats(self):
  candidates=list(getattr(self,'candidates',[]) or [])
  accepted=[c for c in candidates if c.get('keep') and not c.get('rejected')]
  rejected=[c for c in candidates if c.get('rejected')]
  manual=[c for c in candidates if 'manual' in str(c.get('source','')).lower()]
  suggested=[c for c in candidates if c.get('suggested')]
  # Current suggested flags are cleared when the user makes a decision;
  # therefore accepted/rejected are review decisions, not proven detector errors.
  return {'Total candidates':len(candidates),'Currently recommended':len(suggested),
   'Accepted boundaries':len(accepted),'Rejected boundaries':len(rejected),
   'Manually added boundaries':len(manual),
   'Accepted manual boundaries':sum(bool(c.get('keep') and not c.get('rejected')) for c in manual),
   'Rejected manual boundaries':sum(bool(c.get('rejected')) for c in manual),
   'Review only / undecided':sum(not c.get('keep') and not c.get('rejected') and not c.get('suggested') for c in candidates)}
 def detection_feedback_modes(self):
  if not getattr(self,'video',None):return []
  if not (getattr(self,'auto_visual_times',None) or getattr(self,'auto_black_intervals',None)):
   return []
  rows=[]
  for mode in ('Conservative','Balanced','Aggressive'):
   results=self.detection_candidates_for_mode(mode)
   rows.append((mode,len(results),sum(tier=='High' for _,tier,_ in results),
    sum(tier=='Medium' for _,tier,_ in results),sum(tier=='Low' for _,tier,_ in results)))
  return rows
 def update_detection_feedback(self):
  if not hasattr(self,'detection_feedback_summary'):return
  stats=self.detection_feedback_stats()
  self.detection_feedback_summary.setText('  •  '.join(f'{key}: {value}' for key,value in stats.items()))
  modes=self.detection_feedback_modes()
  if modes:
   self.detection_feedback_comparison.setText('Mode comparison (current scan evidence):\n'+
    '\n'.join(f'{mode}: {total} suggested (High {high}, Medium {medium}, Low {low})'
     for mode,total,high,medium,low in modes))
  else:
   self.detection_feedback_comparison.setText('Run Auto Suggest Cuts to compare sensitivity modes.')
 def save_detection_report(self):
  if not self.video or not self.candidates:
   QMessageBox.information(self,'Nothing to report','Load and scan a recording first.');return
  default=str(Path.home()/'Desktop'/(safe_folder_name(Path(self.video).stem)+'_detection_report.csv'))
  path,_=QFileDialog.getSaveFileName(self,'Save detection report',default,'CSV files (*.csv)')
  if not path:return
  try:
   with open(path,'w',newline='',encoding='utf-8-sig') as f:
    writer=csv.writer(f)
    writer.writerow(['Detection Feedback Report','Commercial Splitter 4.6.31'])
    writer.writerow(['Source video',Path(self.video).name])
    writer.writerow(['Duration (seconds)',f'{self.duration:.3f}'])
    writer.writerow(['Current sensitivity',self.detection_sensitivity.currentText()])
    writer.writerow(['Generated at',time.strftime('%Y-%m-%d %I:%M:%S %p')])
    writer.writerow([])
    writer.writerow(['Review statistic','Count'])
    for label,count in self.detection_feedback_stats().items():writer.writerow([label,count])
    writer.writerow([])
    writer.writerow(['Sensitivity mode','Suggested boundaries','High','Medium','Low'])
    for row in self.detection_feedback_modes():writer.writerow(row)
    writer.writerow([])
    writer.writerow(['time_seconds','time_display','review_state','currently_suggested','accepted','rejected','manually_added','confidence_label','reason','source'])
    for c in sorted(self.candidates,key=lambda x:float(x['time'])):
     t=float(c['time']);accepted=bool(c.get('keep') and not c.get('rejected'))
     rejected=bool(c.get('rejected'));suggested=bool(c.get('suggested'))
     state='Accepted' if accepted else 'Rejected' if rejected else 'Recommended' if suggested else 'Review Only'
     writer.writerow([f'{t:.3f}',fmt(t),state,int(suggested),int(accepted),int(rejected),
      int('manual' in str(c.get('source','')).lower()),c.get('confidence',''),c.get('reason',''),c.get('source','')])
  except OSError as e:
   QMessageBox.warning(self,'Report error',str(e));return
  self.status.setText(f'Detection feedback report saved: {Path(path).name}')
  QMessageBox.information(self,'Report saved',f'Saved review summary, available mode comparisons, and {len(self.candidates)} candidates to:\n{path}\n\nReview counts are not ground-truth accuracy measurements.')

 def refresh_selected_review_preview(self):
  listing=self.accepted_list if self.active_queue=='accepted' else self.candidate_list
  if listing.currentItem() is not None:self.show_candidate(listing.currentRow())
  else:
   self.preview_generation+=1
   self.review_video.setText('No cut selected')
   for widget in (self.before_preview,self.after_preview):
    widget.clear();widget.setText('No preview')

 def show_candidate(self,row):
  i=self.candidate_index()
  if i is None or i<0 or i>=len(self.candidates):return
  t=float(self.candidates[i]['time']);self.preview_generation+=1;generation=self.preview_generation
  for previous in list(self.frame_processes.values()):
   if previous.state()!=QProcess.NotRunning:
    previous.blockSignals(True);previous.kill()
   previous.deleteLater()
  self.frame_processes.clear()
  candidate=self.candidates[i]
  status='ACCEPTED' if candidate.get('keep') and not candidate.get('rejected') else ('REJECTED' if candidate.get('rejected') else 'SUGGESTED')
  confidence=str(candidate.get('confidence','unknown')).upper()
  self.review_video.setText(f'CUT  {fmt(t)}     •     {status}     •     {confidence} confidence')
  self.before_preview.clear();self.before_preview.setText('Loading frame…')
  self.after_preview.clear();self.after_preview.setText('Loading frame…')
  # Debounce rapid review-list navigation. Only the final highlighted cut
  # launches FFmpeg, preventing a queue of decoders when arrowing through cuts.
  def load_selected_frames():
   if generation!=self.preview_generation or not self.video:return
   self.request_preview(self.before_preview,max(0,t-1/max(1.,self.fps)),generation)
   self.request_preview(self.after_preview,min(max(0,self.duration-0.001),t),generation)
  QTimer.singleShot(120,load_selected_frames)
 def set_cut(self,keep):
  i=self.candidate_index()
  if i is None or i<0:return
  listing=self.accepted_list if self.active_queue=='accepted' else self.candidate_list
  position=listing.currentRow()
  visible=[listing.item(row).data(Qt.UserRole) for row in range(listing.count())]
  self.timeline_snapshot()
  self.candidates[i]['keep']=keep;self.candidates[i]['rejected']=not keep;self.candidates[i].pop('suggested',None)
  next_index=visible[position+1] if position+1<len(visible) else i
  self.sync_candidates(focus=next_index,queue='scanned' if self.active_queue=='scanned' else 'accepted')
  self.save_recovery()
 def delete_review_candidate(self):
  """Remove a scanned suggestion without touching accepted export boundaries."""
  if not self.video or self.busy:return
  item=self.candidate_list.currentItem()
  if item is None:return
  index=item.data(Qt.UserRole)
  if not isinstance(index,int) or not 0<=index<len(self.candidates):return
  candidate=self.candidates[index]
  if candidate.get('keep') and not candidate.get('rejected'):
   QMessageBox.information(self,'Accepted cut','This cut is accepted for export. Remove it from Accepted Cuts first if you want to delete the review entry.')
   return
  t=float(candidate.get('time',0))
  self.timeline_snapshot()
  del self.candidates[index]
  self.active_queue='scanned'
  remaining=[self.candidate_list.item(j).data(Qt.UserRole) for j in range(self.candidate_list.count()) if j!=self.candidate_list.currentRow()]
  next_focus=next((old-1 if old>index else old for old in remaining if old!=index),None)
  self.sync_candidates(focus=next_focus,queue='scanned')
  self.refresh_selected_review_preview()
  self.save_recovery()
  self.status.setText(f'Deleted review suggestion at {fmt(t)}')
 def clear_unaccepted_review_candidates(self):
  """Delete only unaccepted review candidates; retain manual/accepted cuts."""
  if not self.video or self.busy:return
  count=sum(not (c.get('keep') and not c.get('rejected')) for c in self.candidates)
  if not count:
   self.status.setText('No unaccepted review suggestions to remove');return
  answer=QMessageBox.question(self,'Clear review suggestions',f'Delete {count} unaccepted review entries?\n\nAccepted cuts and export boundaries will remain unchanged.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
  if answer!=QMessageBox.Yes:return
  self.timeline_snapshot()
  self.candidates=[c for c in self.candidates if c.get('keep') and not c.get('rejected')]
  self.active_queue='scanned';self.sync_candidates(queue='scanned');self.save_recovery()
  self.status.setText(f'Cleared {count} unaccepted review suggestions; accepted cuts preserved')
 def delete_accepted_cut(self):
  if not self.video or self.busy:return
  item=self.accepted_list.currentItem()
  if item is None:return
  i=item.data(Qt.UserRole)
  if i is None or not 0<=i<len(self.candidates):return
  row=self.accepted_list.currentRow()
  self.timeline_snapshot()
  self.candidates[i]['keep']=False;self.candidates[i]['rejected']=True;self.candidates[i].pop('suggested',None)
  remaining=[self.accepted_list.item(j).data(Qt.UserRole) for j in range(self.accepted_list.count()) if j!=row]
  focus=remaining[min(row,len(remaining)-1)] if remaining else i
  self.sync_candidates(focus=focus,queue='accepted' if remaining else 'scanned')
  self.refresh_selected_review_preview()
  self.save_recovery()
  self.status.setText('Accepted cut removed; available in Scanned Scenes for recovery')
 def accept_double_clicked_candidate(self,item):
  """Accept the exact scanned candidate that was double-clicked."""
  if not self.video or self.busy or item is None:return
  index=item.data(Qt.UserRole)
  if not isinstance(index,int) or not 0<=index<len(self.candidates):return
  candidate=self.candidates[index]
  if candidate.get('keep'):
   self.status.setText('This cut is already accepted')
   return
  self.timeline_snapshot()
  candidate['keep']=True
  candidate['rejected']=False
  candidate.pop('suggested',None)
  self.sync_candidates(focus=index,queue='accepted')
  self.save_recovery()
  self.status.setText(f'Accepted cut at {fmt(float(candidate["time"]))} (double-click)')
 def workspace_play_pause(self):
  """Route the Play/Pause shortcut to the visible workspace."""
  current=self.stack.currentIndex()
  if current==3:
   self.toggle_export_play()
  elif current==2:
   if self.timeline_review_tabs.currentIndex()==0:self.timeline_toggle()
  # Import, dashboard, and the review list have no embedded player.
 def accept_cut(self):self.set_cut(True)
 def reject_cut(self):self.set_cut(False)
 def nudge_cut(self,direction):
  i=self.candidate_index()
  if i is None or i<0:return
  fps=self.fps
  steps=[1/fps,5/fps,.5,1,5,10]
  amount=steps[self.move_step.currentIndex()]
  t=max(0.001,min(self.duration-.001,self.candidates[i]['time']+direction*amount))
  self.candidates[i]['time']=round(t,3);self.sync_candidates(focus=i);self.save_recovery()
 def preview_review(self):
  i=self.candidate_index()
  if i is None or i<0:return
  # Play forward from the exact selected boundary, never a lead-in from before it.
  start=max(0.,float(self.candidates[i]['time']))
  later=[t for t in self.cuts if t>start+.001]
  end=min(self.duration,start+15.,min(later) if later else self.duration)
  self.play_range(start,end)
 def play_range(self,a,b):
  if not self.video or b<=a:
   QMessageBox.warning(self,'Nothing to preview','Choose a valid clip before previewing.');return
  ff=tool('ffmpeg');player=tool('ffplay')
  if not ff or not player:
   QMessageBox.warning(self,'Preview tools missing','Both ffmpeg.exe and ffplay.exe are required for frame-accurate Review previews.');return
  # ffplay -ss can land on a nearby keyframe. Decode from the source and
  # re-encode only the short requested interval for frame-accurate playback.
  duration=b-a
  fd,clip=tempfile.mkstemp(prefix='commercial_splitter_review_',suffix='.mkv')
  os.close(fd)
  try:os.unlink(clip)
  except OSError:pass
  log_load(f'REVIEW PREVIEW exact start={a:.3f} end={b:.3f} duration={duration:.3f}')
  encoder=QProcess(self);self.playback_processes.append(encoder)
  encoder.setProgram(ff)
  encoder.setArguments(['-hide_banner','-loglevel','error','-y','-i',self.video,
                        '-ss',f'{a:.6f}','-t',f'{duration:.6f}',
                        '-map','0:v:0','-map','0:a:0?',
                        '-c:v','mpeg4','-q:v','3','-c:a','aac',
                        '-avoid_negative_ts','make_zero',clip])
  def cleanup():
   try:os.unlink(clip)
   except OSError:pass
  def encoder_done(code,status):
   error=bytes(encoder.readAllStandardError()).decode('utf-8','replace')[-1800:]
   if encoder in self.playback_processes:self.playback_processes.remove(encoder)
   encoder.deleteLater()
   if code!=0 or not Path(clip).is_file() or Path(clip).stat().st_size==0:
    cleanup();QMessageBox.warning(self,'Review preview failed',error.strip() or 'FFmpeg could not prepare the preview.');return
   proc=QProcess(self);self.playback_processes.append(proc)
   proc.setProgram(player)
   proc.setArguments(['-hide_banner','-loglevel','warning','-autoexit',
                      '-window_title',f'Commercial Splitter — from {fmt(a)}',
                      '-i',clip])
   def player_done(code,status):
    if proc in self.playback_processes:self.playback_processes.remove(proc)
    proc.deleteLater();cleanup()
   proc.finished.connect(player_done)
   proc.errorOccurred.connect(lambda error:log_load('REVIEW PLAYER ERROR: '+proc.errorString()))
   proc.start()
  encoder.finished.connect(encoder_done)
  encoder.errorOccurred.connect(lambda error:log_load('REVIEW ENCODE ERROR: '+encoder.errorString()))
  self.status.setText(f'Preparing frame-accurate preview from {fmt(a)}…')
  encoder.start()
 def choose_output(self):
  path=QFileDialog.getExistingDirectory(self,'Choose export folder',self.output_dir.text() or str(Path.home()))
  if path:self.output_dir.setText(path)
 def cancel_export(self):
  if not self.export_worker:return
  self.cancel_export_btn.setEnabled(False);self.status.setText('Cancelling export…')
  self.export_worker.request_cancel()
 def preset_changed(self,name):
  self.prefs['export_preset']=name;self.save_preferences(self.prefs)
  if name=='Original Streams (Fast copy)':self.export_mode.setCurrentText('Fast copy')
  else:self.export_mode.setCurrentText('Accurate')
 def selected_export_rows(self):
  rows=[];seen=set()
  for i in self.normalized_clip_order():
   a,b=self.segments()[i];name,include=self.export_names.get(i,(None,None))
   if not name or not include.isChecked():continue
   filename=name.text().strip()
   if not filename.lower().endswith('.mp4'):filename+='.mp4'
   if any(ch in filename for ch in '<>:"/\\|?*') or filename.endswith(('.', ' ')):
    raise ValueError(f'Invalid filename for clip {i+1}')
   if filename.casefold() in seen:raise ValueError(f'Duplicate filename: {filename}')
   seen.add(filename.casefold());rows.append((i+1,a,b,filename))
  return rows
 def restore_export_queue(self):
  jobs=[]
  for entry in self.prefs.get('export_queue',[]):
   try:
    video,folder,rows,mode,preset=entry
    if isinstance(video,str) and isinstance(folder,str) and isinstance(rows,list) and mode in ('Accurate','Fast copy'):
     jobs.append((video,folder,[tuple(r) for r in rows if isinstance(r,(tuple,list)) and len(r)==4],mode,str(preset)))
   except (ValueError,TypeError):continue
  return jobs
 def persist_export_queue(self):
  self.prefs['export_queue']=self.export_queue
  self.save_preferences(self.prefs)
 def add_export_queue(self):
  if not self.video:return
  try:rows=self.selected_export_rows()
  except ValueError as e:QMessageBox.warning(self,'Export queue',str(e));return
  if not rows:return
  folder=self.output_dir.text().strip()
  if not folder:QMessageBox.warning(self,'Export queue','Choose an output folder.');return
  self.export_queue.append((self.video,folder,rows,self.export_mode.currentText(),self.export_preset.currentText()))
  self.persist_export_queue();self.refresh_export_queue();self.status.setText(f'Queued {len(rows)} clip(s) from {Path(self.video).name}')
 def refresh_export_queue(self):
  self.queue_list.blockSignals(True);self.queue_list.clear()
  for i,(video,folder,rows,mode,preset) in enumerate(self.export_queue,1):
   item=QListWidgetItem(f'{i:02d}   {Path(video).name}   •   {len(rows)} clips   •   {preset}');item.setToolTip(f'Source: {video}\nOutput: {folder}\nMode: {mode}\nPreset: {preset}\nClips: {len(rows)}');item.setData(Qt.UserRole,i-1);self.queue_list.addItem(item)
  self.queue_list.blockSignals(False)
  if hasattr(self,'queue_summary'):
   self.queue_summary.setText(f'Pending jobs: {len(self.export_queue)}  •  Completed: {self.queue_completed}  •  Failed: {self.queue_failed}'+('  •  Paused' if self.export_queue_paused else ''))
 def queue_rows_moved(self,*args):
  # QListWidget already reflects the requested order after the move.
  order=[]
  for i in range(self.queue_list.count()):
   item=self.queue_list.item(i)
   # Each row stores a stable job identifier through its original object reference.
   key=item.data(Qt.UserRole)
   if isinstance(key,int) and 0<=key<len(self.export_queue):order.append(self.export_queue[key])
  if len(order)==len(self.export_queue):self.export_queue=order;self.persist_export_queue()
  self.refresh_export_queue()
 def remove_export_queue(self):
  indices=sorted({x.row() for x in self.queue_list.selectedIndexes()},reverse=True)
  for index in indices:
   if 0<=index<len(self.export_queue):self.export_queue.pop(index)
  if indices:self.persist_export_queue();self.refresh_export_queue()
 def retry_failed_queue(self):
  failures=self.prefs.get('failed_export_jobs',[])
  if not failures:self.status.setText('No failed jobs to retry');return
  for entry in failures:
   try:
    video,folder,rows,mode,preset=entry
    self.export_queue.append((video,folder,[tuple(r) for r in rows],mode,preset))
   except (ValueError,TypeError):continue
  self.prefs['failed_export_jobs']=[];self.queue_failed=0;self.persist_export_queue();self.refresh_export_queue()
 def clear_export_queue(self):
  self.export_queue.clear();self.persist_export_queue();self.refresh_export_queue()
 def stop_export_queue(self):
  # Stop immediately: cancel active FFmpeg, preserve pending jobs for later.
  self.queue_stop_requested=True
  if self.export_queue_paused:
   self.export_queue_paused=False
   self.queue_pause_btn.blockSignals(True);self.queue_pause_btn.setChecked(False);self.queue_pause_btn.blockSignals(False)
   self.queue_pause_btn.setText('Pause After Clip')
  if self.export_worker is not None:self.export_worker.request_cancel()
  self.status.setText('Stopping queue — cancelling active clip; pending jobs are preserved')
  self.refresh_export_queue()
 def set_queue_pause(self,paused):
  self.export_queue_paused=paused
  self.queue_pause_btn.setText('Resume Queue' if paused else 'Pause After Clip')
  if self.export_worker is not None:
   self.export_worker.pause_after_clip.set() if paused else self.export_worker.pause_after_clip.clear()
  self.status.setText('Pause requested — waiting for current clip to finish' if paused else 'Export queue resumed')
  self.refresh_export_queue()
  if not paused and not self.busy and not self.queue_stop_requested:self.run_export_queue()
 def run_export_queue(self):
  if self.busy or self.export_queue_paused or not self.export_queue:return
  self.queue_stop_requested=False
  job=self.export_queue[0]
  video,folder,rows,mode,preset=job
  if not Path(video).is_file():
   QMessageBox.warning(self,'Queue',f'Source video missing: {video}');return
  if not self.start_export_job(video,folder,rows,mode,preset):return
  self.active_queue_job=job
  self.export_queue.pop(0);self.persist_export_queue();self.refresh_export_queue()
 def show_export_history(self):
  dialog=QDialog(self);dialog.setWindowTitle('Export History');dialog.resize(900,420)
  layout=QVBoxLayout(dialog);table=QTableWidget(dialog)
  history=self.prefs.get('export_history',[]);table.setColumnCount(5);table.setRowCount(len(history))
  table.setHorizontalHeaderLabels(['Date','Recording','Clips','Preset','Result'])
  for i,entry in enumerate(reversed(history)):
   for j,key in enumerate(('date','video','clips','preset','result')):table.setItem(i,j,QTableWidgetItem(str(entry.get(key,''))))
  table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);layout.addWidget(table)
  close=QPushButton('Close');close.clicked.connect(dialog.accept);layout.addWidget(close);dialog.exec()
 def record_export_history(self,result,clips):
  entry={'date':time.strftime('%Y-%m-%d %I:%M:%S %p'),'video':Path(getattr(self,'active_export_video',self.video) or '').name,'clips':clips,'preset':getattr(self,'active_export_preset','Balanced'),'result':result}
  history=self.prefs.setdefault('export_history',[]);history.append(entry);self.prefs['export_history']=history[-100:];self.save_preferences(self.prefs)
 def start_export_job(self,video,folder,rows,mode,preset):
  try:Path(folder).expanduser().mkdir(parents=True,exist_ok=True)
  except OSError as e:QMessageBox.warning(self,'Export folder',str(e));return False
  existing=[name for _,_,_,name in rows if (Path(folder)/name).exists()]
  if existing and QMessageBox.question(self,'Overwrite?',f'{len(existing)} files exist. Overwrite them?')!=QMessageBox.Yes:return False
  self.last_export_folder=str(Path(folder).resolve());self.active_export_video=video;self.active_export_preset=preset;self.export_started_at=time.monotonic()
  self.busy=True;self.export_btn.setEnabled(False);self.cancel_export_btn.setEnabled(True);self.progress.setValue(0)
  self.export_run_total=len(rows);self.export_run_completed=0;self.export_run_failed=0
  self.export_eta.setText(f'Preparing export: 0/{len(rows)} clips')
  worker=Worker('export',video);worker.extra=(str(folder),rows,mode,preset)
  if self.export_queue_paused:worker.pause_after_clip.set()
  self.export_worker=worker;self.task(worker,self.export_done);return True
 def export_native(self):
  if not self.video or self.busy:return
  try:rows=self.selected_export_rows()
  except ValueError as e:QMessageBox.warning(self,'Invalid filename',str(e));return
  if not rows:QMessageBox.warning(self,'No clips','Select at least one clip.');return
  folder=self.output_dir.text().strip()
  if not folder:QMessageBox.warning(self,'Export folder','Choose an export folder first.');return
  self.start_export_job(self.video,folder,rows,self.export_mode.currentText(),self.export_preset.currentText())
 def show_export_results(self):
  checks=getattr(self,'last_export_checks',[])
  if not checks:
   QMessageBox.information(self,'Export results','No completed export results in this session.');return
  dialog=QDialog(self);dialog.setWindowTitle('Export Verification Results');dialog.resize(1040,540)
  layout=QVBoxLayout(dialog)
  passed=sum(1 for r in checks if r[4]=='PASS' and r[6]=='SIMILAR')
  summary=QLabel(f'{len(checks)} exported clip(s) • {passed} passed duration and visual similarity checks • {len(checks)-passed} need review')
  summary.setWordWrap(True);layout.addWidget(summary)
  table=QTableWidget(len(checks),7,dialog)
  table.setHorizontalHeaderLabels(['Clip','Filename','Expected (mm:ss)','Actual (mm:ss)','Duration','First frame','Last frame'])
  table.setEditTriggers(QTableWidget.NoEditTriggers)
  table.setSelectionBehavior(QTableWidget.SelectRows)
  table.setAlternatingRowColors(True)
  for i,r in enumerate(checks):
   idx,name,expected,actual,status,details,boundary,first,last,boundary_details=r
   values=[str(idx),str(name),fmt(float(expected)),fmt(float(actual)) if actual else '—',str(status),str(first) if first!='' else '—',str(last) if last!='' else '—']
   for j,value in enumerate(values):
    cell=QTableWidgetItem(value)
    if j==4:
     cell.setToolTip(str(details))
    if j in (5,6):
     cell.setToolTip(f'{boundary}: {boundary_details}\nVisual error; lower means closer match.')
    if j==4 and status!='PASS' or j in (5,6) and boundary!='SIMILAR':
     cell.setForeground(QColor('#e6ad56'))
    table.setItem(i,j,cell)
  table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
  for col in (0,2,3,4,5,6):table.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeToContents)
  layout.addWidget(table,1)
  hint=QLabel('First/last values are visual difference scores (lower is better). SIMILAR is a heuristic comparison against nearby source frames, not proof of exact frame identity. Hover over a cell for verification details.')
  hint.setWordWrap(True);layout.addWidget(hint)
  actions=QHBoxLayout()
  open_folder=QPushButton('Open Export Folder');open_folder.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_export_folder)) if self.last_export_folder else None)
  actions.addWidget(open_folder)
  open_csv=QPushButton('Open CSV Report');open_csv.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.last_export_folder)/'export_verification.csv'))) if self.last_export_folder else None)
  actions.addWidget(open_csv);actions.addStretch()
  close=QPushButton('Close');close.clicked.connect(dialog.accept);actions.addWidget(close)
  layout.addLayout(actions);dialog.exec()
 def show_export_complete(self,count):
  self.show_export_results()
 def export_done(self,kind,data):
  if kind=='export_clip_started':
   i,total,index,name=data
   self.export_eta.setText(f'Encoding clip {i}/{total} (#{index}): {name}')
   self.status.setText(f'Exporting {i}/{total}: {name}')
  elif kind=='export_clip_failed':
   i,total,index,name,reason,completed,checks=data
   self.busy=False;self.export_worker=None;self.export_btn.setEnabled(True);self.cancel_export_btn.setEnabled(False)
   self.export_run_failed=1;self.export_run_completed=completed
   self.last_export_checks=list(checks);self.results_btn.setEnabled(bool(checks))
   self.progress.setValue(round(completed/max(1,total)*100))
   self.export_eta.setText(f'Export stopped: {completed} succeeded, 1 failed, {max(0,total-i)} not attempted')
   self.status.setText(f'Export failed on clip {i}/{total}: {name}')
   self.record_export_history('Partially completed' if completed else 'Failed',completed)
   if self.active_queue_job is not None:
    self.prefs.setdefault('failed_export_jobs',[]).append(self.active_queue_job)
    self.active_queue_job=None;self.queue_failed+=1;self.save_preferences(self.prefs);self.refresh_export_queue()
   QMessageBox.warning(self,'Export stopped on a clip',
    f'Clip {i}/{total} (source clip #{index})\n{name}\n\n'
    f'{completed} succeeded • 1 failed • {max(0,total-i)} not attempted\n\n'
    f'FFmpeg / export error:\n{reason[-1400:]}\n\n'
    'Successfully exported clips are kept. The incomplete run does not replace your prior CSV manifests.')
   if self.export_queue and not self.export_queue_paused and not self.queue_stop_requested:QTimer.singleShot(100,self.run_export_queue)
  elif kind=='export_progress':
   i,total,name=data;self.export_run_completed=i;self.progress.setValue(round(i/total*100));self.status.setText(f'Exported {i}/{total}: {name}')
   elapsed=max(.01,time.monotonic()-(self.export_started_at or time.monotonic()))
   remaining=round(elapsed/i*(total-i)) if i else 0
   self.export_eta.setText(f'{i}/{total} clips • estimated remaining {remaining//60}m {remaining%60}s')
  elif kind=='export_paused':
   done,total=data
   self.status.setText(f'Export paused after {done}/{total} clips — click Resume Queue to continue')
   self.export_eta.setText(f'Paused after {done}/{total} clips')
  elif kind=='export_done':
   self.busy=False;self.export_worker=None;self.export_btn.setEnabled(True);self.cancel_export_btn.setEnabled(False)
   count,checks=data
   self.last_export_checks=list(checks);self.results_btn.setEnabled(bool(checks))
   warnings=[item for item in checks if item[4]!='PASS' or item[6] in ('REVIEW','NOT CHECKED')]
   self.status.setText(f'Export complete: {count} succeeded, 0 failed, 0 skipped; {len(warnings)} verification warning(s)')
   self.record_export_history('Completed',count);self.export_eta.setText('Export completed');self.show_export_complete(count)
   if self.active_queue_job is not None:self.queue_completed+=1;self.active_queue_job=None;self.refresh_export_queue()
   if self.export_queue and not self.export_queue_paused and not self.queue_stop_requested:QTimer.singleShot(100,self.run_export_queue)
  elif kind=='export_cancelled':
   done,total=data;self.busy=False;self.export_worker=None;self.export_btn.setEnabled(True);self.cancel_export_btn.setEnabled(False)
   self.status.setText(f'Cancelled: {done} succeeded, 0 failed, {total-done} skipped');self.export_eta.setText(f'Cancelled: {done} succeeded, {total-done} skipped');self.record_export_history('Cancelled',done)
   if self.active_queue_job is not None:
    self.export_queue.insert(0,self.active_queue_job);self.active_queue_job=None;self.persist_export_queue();self.refresh_export_queue()
  elif kind=='error':
   self.busy=False;self.export_worker=None;self.export_btn.setEnabled(True);self.cancel_export_btn.setEnabled(False);self.record_export_history('Failed',0)
   if self.active_queue_job is not None:
    self.prefs.setdefault('failed_export_jobs',[]).append(self.active_queue_job);self.active_queue_job=None;self.queue_failed+=1;self.save_preferences(self.prefs);self.refresh_export_queue()
   QMessageBox.warning(self,'Export failed',str(data))
   if self.export_queue and not self.export_queue_paused and not self.queue_stop_requested:QTimer.singleShot(100,self.run_export_queue)

STYLE='''
QWidget {background:#11151c;color:#eaf0f7;font-family:"Segoe UI";font-size:13px;}
QMainWindow {background:#11151c;}
QLabel#brand {font-size:20px;font-weight:700;color:#f3f6fb;}
QLabel#heading {font-size:27px;font-weight:700;color:#f3f6fb;}
QLabel#muted {color:#9aaabd;}
QLabel#dropTitle {font-size:23px;font-weight:700;color:#f3f6fb;background:transparent;border:none;}
QLabel#dropSubtitle {font-size:13px;color:#b8c8d9;background:transparent;border:none;}
QLabel#importHeading {font-size:23px;font-weight:700;color:#f3f6fb;}
QLabel#dashboardCount {color:#83b6e5;font-weight:700;letter-spacing:1px;}
QLabel#importFileInfo {background:#1b2430;border:1px solid #344356;border-radius:9px;padding:12px 16px;color:#b8c8d9;}
QFrame#dropzone {background:#1a222e;border:2px dashed #6581a2;border-radius:16px;}
QFrame#previewPanel {background:#1b2430;border:1px solid #344356;border-radius:14px;}
QLabel#framePreview {background:#111922;border:1px solid #344356;border-radius:9px;color:#9aacc0;font-size:16px;}
QPushButton {background:#222c39;border:1px solid #344254;border-radius:9px;padding:11px 18px;font-weight:600;}
QPushButton:hover {background:#2b3a4b;border-color:#5684b5;}
QPushButton:checked,QPushButton#primary {background:#326baf;border-color:#4684c9;color:#fff;}
QPushButton#primary:hover {background:#4080ca;}
QPushButton#quiet {background:transparent;border:1px solid #2d3949;color:#aebed0;}
QPushButton#sectionNav {padding:9px 17px;border-radius:8px;font-size:13px;font-weight:600;border:1px solid #435269;background:#222c39;}
QPushButton#sectionNav:hover:!checked {background:#344457;border-color:#7191b8;}
QPushButton#sectionNav:checked {background:#326baf;border:1px solid #6a9ed8;color:white;}
QPushButton:disabled {color:#778596;background:#1a222c;border-color:#283443;}
QPushButton:focus {border:2px solid #78b4f4;}
QListWidget::item {padding:5px 7px;}
QListWidget::item:selected {background:#315579;color:#fff;border-radius:4px;}
QGroupBox {border:1px solid #344356;border-radius:9px;margin-top:12px;padding-top:9px;font-weight:600;}
QGroupBox::title {subcontrol-origin:margin;left:12px;padding:0 5px;}
QSplitter::handle {background:#293647;}
QSplitter::handle:hover {background:#4684c9;}
QToolTip {background:#263548;color:#f0f5fc;border:1px solid #58718c;padding:5px;border-radius:5px;}

QLabel#exportStill {background:#171d27;border-radius:8px;}
QFrame#clipPanel {background:#1b2430;border:1px solid #344356;border-radius:12px;}
QListWidget,QLineEdit,QDoubleSpinBox,QComboBox {background:#1b2430;border:1px solid #344356;border-radius:6px;padding:7px;}
QPushButton#clipcard {text-align:left;background:#1b2430;border:1px solid #344356;border-radius:12px;padding:15px;}
QPushButton#clipcard:checked {border:2px solid #5c9de3;background:#223449;}
QScrollArea#scroll {border:0;background:transparent;}
QMenuBar {background:#151c26;padding:4px;}QMenuBar::item:selected {background:#2c3c4d;}
QMenu {background:#1b2430;border:1px solid #3b4b5e;}QMenu::item:selected {background:#315579;}
'''
# Light setting uses a comfortable charcoal-gray workspace instead of near-white.
# Substitute colors in a single pass so palette entries cannot cascade.
_LIGHT_PALETTE={
 '#11151c': '#696c62',
 '#eaf0f7': '#f0f2f5',
 '#f3f6fb': '#ffffff',
 '#1a222e': '#76796f',
 '#1b2430': '#73766c',
 '#111922': '#56594f',
 '#171d27': '#5d6056',
 '#222c39': '#828579',
 '#344254': '#96998e',
 '#344356': '#92958a',
 '#41516a': '#8c97a4',
 '#9aaabd': '#d1d9e2',
 '#9aacc0': '#d0d9e4',
 '#aebed0': '#e0e6ed',
 '#151c26': '#606359',
 '#2d3949': '#999c90',
 '#2b3a4b': '#888b80',
 '#2c3c4d': '#7d8176',
 '#3b4b5e': '#8994a0',
 '#315579': '#536f8b',
 '#223449': '#41586e',
 '#1a222c': '#64675d',
 '#283443': '#79838f',
 '#293647': '#737e89',
 '#263548': '#3d4c5b',
 '#f0f5fc': '#f5f7fa',
 '#58718c': '#9badbf',
 '#778596': '#c0cad5',
}
LIGHT_STYLE=re.sub(r'#[0-9a-fA-F]{6}',lambda match:_LIGHT_PALETTE.get(match.group(0).lower(),match.group(0)),STYLE)
LIGHT_STYLE += '''
QLabel#dropTitle,QLabel#importHeading {color:#f0f3f8;}
QLabel#dashboardCount {color:#e2e9d3;}
QLabel#dropSubtitle,QLabel#importFileInfo {color:#e1e8f0;}
QFrame#dropzone {background:#5d6056;border-color:#b0b4a3;}
QLabel#importFileInfo {background:#64675d;border-color:#92958a;}
'''

# Inspector uses the item's foreground for cut type, including on selection.
STYLE += '''
QListWidget#cutInspectorList::item {padding:6px 8px;border-radius:5px;}
QListWidget#cutInspectorList::item:selected {background:#29445d;border:1px solid #78a8d5;}
QListWidget#cutInspectorList::item:hover:!selected {background:#344455;}
'''
LIGHT_STYLE += '''
QListWidget#cutInspectorList::item {padding:6px 8px;border-radius:5px;}
QListWidget#cutInspectorList::item:selected {background:#4b665b;border:1px solid #b4c2a6;}
QListWidget#cutInspectorList::item:hover:!selected {background:#777b70;}
'''
if __name__=='__main__':
 app=QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet(STYLE)
 window=Main();window.setWindowIcon(QIcon(str((ROOT/'commercial_splitter.ico') if (ROOT/'commercial_splitter.ico').exists() else (ROOT.parent/'assets'/'commercial_splitter.ico'))));window.show();sys.exit(app.exec())
