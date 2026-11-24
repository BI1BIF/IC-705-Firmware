const canvas = document.querySelector("#screen");
const ctx = canvas.getContext("2d", {alpha: false});
const controls = document.querySelector("#controls");
const source = document.querySelector("#position-source");
const status = document.querySelector("#announcement");
const asset = name => new URL("./aprs-panel/" + name, import.meta.url);
const images = new Map();
const stack = [{name: "fm"}];
const records = [];
const current = () => stack.at(-1);
const sources = {"NO FIX": 0, GPS: 1, MANUAL: 2};
const calls = {position:"N0DEMO-9", weather:"N0WX-1", message:"N0MSG-2", status:"N0BASE", igate:"N0GATE-10", relayed:"N0HOME-3"};
const noMotion = matchMedia("(prefers-reduced-motion: reduce)");
let frames, timer, sequence = 0, english = false;
try { english = localStorage.getItem("ic705-language") === "en"; } catch {}
if (english) {
  document.documentElement.lang = "en";
  document.title = "APRS simulator · IC-705";
  document.querySelectorAll("[data-en]").forEach(el => el.textContent = el.dataset.en);
}
function record(kind, day = "2026-11-25", mode = sources[source.value]) {
  const fixed = kind === "message" || kind === "status";
  const key = kind + "-" + (fixed ? 2 : mode);
  const secs = 15 * 3600 + 22 * 60 + 3 * ++sequence;
  const time = new Date(secs * 1000).toISOString().slice(11,19);
  return {kind, key, time, day, station: calls[kind]};
}
function show(name, options = {}) {
  stack.push({name, page: 0, ...options}); render();
}
function back() {
  if (current().name === "editor" && current().draft) { show("discard"); return; }
  if (stack.length > 1) stack.pop();
  render();
}
function menu(name) {
  stack.length = 1;
  if(name==="beacon" && source.value!=="NO FIX") {
    stack[0]={name:"fm", frame:"beacon"};
    status.textContent=english?"Beacon sent in the replay.":"已在回放中发送信标。";
    render();return;
  }
  show(name);
}
function hot(label,x,y,w,h,action) {
  const button = document.createElement("button");
  button.type = "button";
  button.ariaLabel = label;
  Object.assign(button.style, {left: (100*x/480)+"%", top: (100*y/272)+"%",
    width: (100*w/480)+"%", height: (100*h/272)+"%"});
  button.addEventListener("click",action);
  controls.append(button);
}
function row(i,label,action) { hot(label,55,26+61*i,304,60,action); }
function rightBack() { hot("Back",366,222,58,47,back); }
function pages(view, count) {
  if (view.page > 0) hot("Previous page",366,26,58,88,()=>{view.page--;render();});
  if (view.page+1 < count) hot("Next page",366,120,58,88,()=>{view.page++;render();});
  rightBack();
}
function fill(x,y,w,h,color) {ctx.fillStyle = color; ctx.fillRect(x,y,w,h);}
function text(value,x,y,size=20,color="white",align="left") {
  ctx.font = size+"px Arial, sans-serif"; ctx.textAlign=align;
  ctx.fillStyle=color; ctx.fillText(value,x,y); ctx.textAlign="left";
}
function base(key) {ctx.drawImage(images.get(key),0,0);}
function titleValue(value,x,w,align="center") {
  // Repeat a blank column of the captured header to preserve its native shading.
  ctx.drawImage(images.get("live"),155,3,1,20,x,3,w,20);
  text(value,align==="right"?x+w-4:x+w/2,20,16,"white",align);
}
function makeList(view, items) {
  const count = Math.max(1,Math.ceil(items.length/4));
  view.page = Math.max(0,Math.min(count-1,view.page));
  const days = view.name==="dates", daily=view.name==="day";
  base(days?"dates":daily?"day":"live");
  if (daily) titleValue(view.day,145,190);
  if (view.name==="inbox") titleValue("Inbox",145,190);
  if (view.name==="heard") titleValue("APRS Stations",145,190);
  titleValue((view.page+1)+"/"+count,367,53,"right");
  for(let i=0;i<4;i++){
    const y=26+61*i, item=items[view.page*4+i];
    const selected = i===0 && item !== undefined;
    const bg=selected?"#5b9fc6":"#000", fg=selected?"black":"white";
    fill(55,y,304,60,bg);
    if (item===undefined) continue;
    if (days) {
      text(item,65,y+38,20,fg);
      row(i,item,()=>show("day",{day:item}));
    } else {
      const offset=frames.keys.indexOf(item.key)*122+(selected?0:61);
      ctx.drawImage(images.get("rows"),0,offset,304,60,55,y,304,60);
      const dy=selected?0:24;
      // Replace only the changing clock digits. Colons and the date stay on the native row.
      [210,222,null,240,252,null,269,281].forEach((x,i)=>{
        if(x!==null)ctx.drawImage(images.get("digits"),12*Number(item.time[i]),dy,12,24,55+x,y+5,12,24);
      });
      if(!item.day.endsWith("-25"))ctx.drawImage(images.get("digits"),12*Number(item.day.at(-1)),dy,12,24,336,y+27,12,24);
      row(i,item.station,()=>show("detail",{item}));
    }
  }
  pages(view,count);
}
function breath(item) {
  const palette=frames.colors[item.kind] || frames.colors.position;
  const [left,top,right,bottom]=frames.edge;
  function paint() {
    const index=noMotion.matches?0:Math.floor(performance.now()/frames.period)%palette.length;
    const color="rgb("+palette[index].join(",")+")";
    fill(left,top,right-left+1,1,color); fill(left,bottom,right-left+1,1,color);
    fill(left,top,1,bottom-top+1,color); fill(right,top,1,bottom-top+1,color);
  }
  paint();
  if (!noMotion.matches && !document.hidden) timer=setInterval(paint,frames.period);
}
function editor(view) {
  const mode=view.mode||"upper";
  base(mode==="upper"?(view.draft?"keyboard-a":"keyboard"):"keyboard-"+mode);
  if(view.draft) {
    fill(55,25,370,40,"black");
    const visible=view.draft.slice(-28);
    text(visible,66,54,22);
    const cursor=Math.min(414,66+ctx.measureText(visible.slice(0,Math.max(0,view.cursor-(view.draft.length-visible.length)))).width);
    fill(cursor,35,2,20,"white");
  }
  function move(delta) {
    view.cursor=Math.max(0,Math.min(view.draft.length,view.cursor+delta));view.last=null;render();
  }
  hot("Cursor left",3,27,49,35,()=>move(-1));hot("Cursor right",428,27,47,35,()=>move(1));
  const groups=mode==="num"?["1","2","3","4","5","6","7","8","9"]:["./@","ABC","DEF","GHI","JKL","MNO","PQRS","TUV","WXYZ"];
  groups.forEach((group,i)=>{
    if(mode==="lower") group=group.toLowerCase();
    hot(group,6+135*(i%3),69+51*Math.floor(i/3),126,44,()=>{
      const now=performance.now();
      if(group.length>1 && view.last?.group===group && now-view.last.time<800) {
        view.cursor--;view.draft=view.draft.slice(0,view.cursor)+view.draft.slice(view.cursor+1);
        insert(view,group[(view.last.index+1)%group.length],{group,time:now,index:(view.last.index+1)%group.length});
      } else insert(view,group[0],{group,time:now,index:0});
    });
  });
  hot("CLR",412,69,61,45,()=>removeChar(view));
  hot("Character type",412,120,61,45,()=>show("types"));
  hot("ENT",412,172,61,45,()=>confirm(view));
  hot("AB / 12",6,222,126,45,()=>{view.mode=mode==="num"?"upper":"num";view.last=null;render();});
  if(mode==="num")hot("0",142,222,126,45,()=>insert(view,"0"));
  else if(view.draft)hot("Case",142,222,126,45,()=>{view.mode=mode==="lower"?"upper":"lower";view.last=null;render();});
  hot("Space",277,222,126,45,()=>insert(view," "));
  hot("Back",412,222,61,45,back);
}
function insert(v,ch,last=null) {
  if(v.draft.length>=67) return;
  v.draft=v.draft.slice(0,v.cursor)+ch+v.draft.slice(v.cursor);v.cursor++;v.last=last;render();
}
function removeChar(v) {
  if(v.cursor>0){v.draft=v.draft.slice(0,v.cursor-1)+v.draft.slice(v.cursor);v.cursor--;}
  v.last=null;render();
}
function confirm(v) {if(v.draft.trim()) {stack.pop();show("review",{draft:v.draft});}}
function edit(draft="") {show("editor",{draft,cursor:draft.length,mode:"upper"});}
function render() {
  clearInterval(timer); controls.replaceChildren();
  const v=current(); canvas.dataset.view=v.name;
  switch(v.name) {
    case "fm": base(v.frame||"fm"); break;
    case "quick": {
      base(v.page?"quick"+(v.page+1):"quick");
      if(v.page===0) ["live","beacon","messages","stations"].forEach((name,i)=>row(i,["APRS RX List","Send APRS Beacon","APRS Messages","APRS Stations"][i],()=>menu(name)));
      if(v.page===1) row(0,"APRS Archive",()=>menu("dates"));
      pages(v,4);break;
    }
    case "live": makeList(v,(v.snapshot||records).slice(0,64));if(v.page>0)v.snapshot ||= records.slice();else delete v.snapshot;break;
    case "dates": makeList(v,[...new Set(records.map(r=>r.day))].sort().reverse());break;
    case "day": makeList(v,records.filter(r=>r.day===v.day));break;
    case "messages": base("messages");row(1,"Inbox",()=>show("inbox"));rightBack();break;
    case "inbox": makeList(v,records.filter(r=>r.kind==="message"));break;
    case "stations": base("stations");["Last Heard","Callsign","Distance"].forEach((name,i)=>row(i,name,()=>show("heard",{sort:i})));rightBack();break;
    case "heard": {
      const seen=new Set();
      const unique=records.filter(r=>{if(seen.has(r.station))return false;seen.add(r.station);return true;});
      if(v.sort===1) unique.sort((a,b)=>a.station.localeCompare(b.station));
      if(v.sort===2) unique.sort((a,b)=>(frames.distance[a.key]??Infinity)-(frames.distance[b.key]??Infinity));
      makeList(v,unique);break;
    }
    case "detail":
      base(v.item.key);breath(v.item);
      if(v.item.kind==="message") hot("Reply",240,220,82,46,()=>edit());
      hot("Back",334,220,82,46,back);break;
    case "editor": editor(v);break;
    case "types": base("key-types");["upper","lower","num","symbol"].forEach((mode,i)=>hot(mode,56,29+48*i,306,44,()=>{
      stack.pop();
      if(mode==="symbol")show("symbols");
      else {current().mode=mode;current().last=null;render();}
    }));rightBack();break;
    case "symbols": {
      base("keyboard-symbol"+(v.page?"2":""));
      const symbols=v.page?">?@[\\]^_`{|}~":" !\"#$%&'()*+,-./:;<=";
      [...symbols].forEach((ch,i)=>hot(ch===" "?"Space":ch,55+61*(i%5),26+61*Math.floor(i/5),60,60,()=>{
        stack.pop();insert(current(),ch);
      }));
      pages(v,2);break;
    }
    case "discard": base("keyboard-exit");hot("Yes",175,171,115,44,()=>{stack.splice(-2);render();});hot("No",300,171,115,44,back);break;
    case "review": {
      const lines=v.draft.match(/.{1,24}/g)||[""];
      const rows=["To  N0MSG-2",...lines,"Send","Edit","Use Quick Text"];
      base("review");
      titleValue((v.page+1)+"/"+Math.ceil(rows.length/4),367,53,"right");
      for(let i=0;i<4;i++){
        const idx=4*v.page+i, value=rows[idx];
        if(!(v.page===0 && (i===0 || (i===1 && value==="A") || (i===2 && value==="Send") || (i===3 && value==="Edit")))){
          fill(55,26+61*i,304,60,"black");
          if(value)text(value,65,64+61*i);
        }
        if(idx===lines.length+1)row(i,"Send",()=>{stack.pop();show("sent");});
        else if(value && idx!==0)row(i,"Edit message "+i,()=>{stack.pop();edit(v.draft);});
      }
      pages(v,Math.ceil(rows.length/4));break;
    }
    case "sent": base("sent");rightBack();break;
    case "beacon": base(source.value==="NO FIX"?"beacon-nofix":"beacon");rightBack();break;
  }
  canvas.ariaLabel=v.item?v.item.station+" · "+v.item.kind:"IC-705 · "+v.name;
  document.querySelectorAll(".sample-buttons button").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.action==="receive:"+v.item?.kind)));
}
function receive(kind) {
  const item=record(kind);records.unshift(item);
  status.textContent=(english?"Received ":"收到 ")+item.station+" · "+item.time;
  if(current().name==="fm") show("detail",{item,incoming:true});
  else if(current().incoming){stack.pop();show("detail",{item,incoming:true});}
  else render();
}
document.addEventListener("click",event=>{
  const trigger=event.target.closest("[data-action]");
  if(!trigger||!frames) return;
  const [name,value]=trigger.dataset.action.split(":");
  if(name==="quick"){if(current().name==="quick")back();else if(current().name==="fm")show("quick");}
  if(name==="exit") back();
  if(name==="receive")receive(value);
});
source.addEventListener("change",()=>{
  const v=current();
  if(v.incoming){const r=v.item;v.item={...r,key:r.kind+"-"+(["message","status"].includes(r.kind)?2:sources[source.value])};}
  if(frames) render();
});
document.addEventListener("keydown",e=>{
  if(!frames || e.target===source) return;
  if(e.key==="Escape"){e.preventDefault();back();return;}
  const v=current();
  if(v.name!=="editor" || e.ctrlKey || e.altKey || e.metaKey) return;
  if(e.key==="Enter")confirm(v);
  else if(e.key==="Backspace")removeChar(v);
  else if(/^[ -~]$/.test(e.key))insert(v,e.key);
  else return;
  e.preventDefault();
});
document.addEventListener("visibilitychange",()=>{if(frames)render();});
noMotion.addEventListener("change",()=>{if(frames)render();});
try {
  const res=await fetch(asset("frames.json"));
  if(!res.ok) throw Error("manifest");
  const data=await res.json();
  const names=[...data.keys,"fm","quick","quick2","quick3","quick4","live","messages","stations","dates","day","beacon","beacon-nofix","keyboard","keyboard-a","keyboard-lower","keyboard-num","keyboard-symbol","keyboard-symbol2","key-types","keyboard-exit","review","sent","rows","digits"];
  await Promise.all(names.map(async name=>{
    const img=new Image();img.src=asset(name+".png");await img.decode();
    if(!["rows","digits"].includes(name) && (img.width!==480 || img.height!==272))throw Error(name);
    images.set(name,img);
  }));
  frames=data;
  [["position","2026-11-23"],["weather","2026-11-24"],["message","2026-11-25"],["status","2026-11-25"]].forEach(([kind,date])=>records.unshift(record(kind,date)));
  render();
  document.querySelectorAll("button[data-action],#position-source").forEach(el=>{el.disabled=false;});
} catch {
  document.querySelector("#load-error").textContent=english?"Could not load firmware frames. Reload to retry.":"固件画面未能载入，请刷新重试。";
}
