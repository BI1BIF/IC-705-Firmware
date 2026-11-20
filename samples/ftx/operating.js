// Page state belongs to this offline FT8/FT4 session. QSO events are UI
// rehearsals only; this module has no connection to a transmitter or audio device.
const station = {call:"",position:"demo",grid:"",audio:"follow",hz:1000,parity:"opposite",
                 sequence:"manual",report:"",limit:3};
let settingsBack="txmenu", settingsTab=0, draft=null, receivedParity=null;
let qso=null, clockTimer=null, rehearsalOffset=0, mapIndex=0, mapBack="list", sessionRevision=0;
const slotMs=()=>ft4?7500:15000;
const nowMs=()=>Date.now()+rehearsalOffset;
const slotId=()=>Math.floor(nowMs()/slotMs());
const side=n=>n===0?"偶":"奇";
const reportText=n=>(Number(n)<0?"-":"+")+String(Math.abs(Number(n))).padStart(2,"0");
function fileParity(name) {
    const m=/^\d{6}_(\d{2})(\d{2})(\d{2})(?:[._](\d))?\.wav$/i.exec(name);
    if (!m || +m[1]>23 || +m[2]>59 || +m[3]>59) return null;
    const ms=(+m[3])*1000+(Number(m[4])||0)*100;
    if (ms%slotMs()!==0) return null;
    return Math.floor(ms/slotMs())%2;
}
function manageClock() {
    if(["preset","loaded","home"].includes(page)) {
        clearInterval(clockTimer);clockTimer=null;
    } else if(clockTimer===null) clockTimer=setInterval(tick,160);
}
function clockBar(parent) {
    const strip=add(parent,"span","","slotclock");
    strip.title="UTC 偶/奇时隙及本时隙剩余秒数";
    for(const n of [0,1]) add(strip,"i",side(n)+(page==="qso" && qso?.txParity===n?" TX":" RX"));
    add(strip,"time","");add(strip,"span","","utc");
    paintClock();
}
function paintClock() {
    const ms=nowMs(),period=slotMs(),frac=(ms%period)/period,parity=Math.floor(ms/period)%2;
    for(const strip of document.querySelectorAll(".slotclock")) {
        strip.querySelectorAll("i").forEach((el,n)=>{
            el.style.setProperty("--fill",n===parity?(100*frac)+"%":"0%");
            el.style.outline=n===parity?"1px solid #8aabb6":"";
        });
        strip.querySelector("time").textContent=((1-frac)*period/1000).toFixed(1)+"s";
        strip.querySelector(".utc").textContent=new Date(ms).toISOString().slice(11,19)+"Z";
    }
}
function stopSession() {sessionRevision++;qso=null;rehearsalOffset=0;}
function leaveStation() {
    stopSession();heard.clear();draft=null;selected=null;rows=[];offset=0;receivedParity=null;
    changePage("home");say("已回到原厂迷你频谱回放。可从 MENU · PRESET 再次进入。");
}
function changePage(next) {page=next;render();}
function openSettings(back) {
    settingsBack=back;settingsTab=0;draft={...station};changePage("settings");
}
function field(form,label,name,options) {
    const l=add(form,"label",label), el=add(l,options?"select":"input","");
    el.id=name;
    if(options) for(const [value,title] of options) add(el,"option",title).value=value;
    el.value=draft[name];
    el.oninput=()=>{draft[name]=el.value.trim();};
    return el;
}
function renderSettings(work,bar) {
    bar.textContent="TX 设置　/　"+(settingsTab?"时隙与应答":"本台与音频");
    const f=add(work,"div","","station-form");
    if(!settingsTab) {
        field(f,"本台呼号","call").maxLength=11;
        const position=field(f,"位置","position",[["demo","示例 GPS"],["gps","GPS 快照"],["grid","手填网格"],["none","无定位"]]);
        const grid=field(f,"本台网格","grid");grid.maxLength=6;
        const updateGrid=()=>{
            draft.position=position.value;grid.readOnly=draft.position!=="grid";
            const site=draft.position==="demo"?[35.5,139.5]:draft.position==="gps"?importedFix:null;
            grid.value=site?grid4(site):grid.readOnly?"—":draft.grid;
        };
        position.oninput=updateGrid;updateGrid();
        const fix=add(f,"button",importedFix?"定位快照有效":"读取 GPS 快照");fix.id="fixStatus";
        fix.onclick=()=>$("gpsFile").click();
        field(f,"TX 音频","audio",[["follow","跟随对台"],["fixed","固定偏移"]]);
        field(f,"固定 / CQ Hz","hz").type="number";
        add(f,"small","RF 频率、功率与 ALC 沿用电台。此处 Hz 是音频偏移。");
    } else {
        field(f,"TX 时隙","parity",[["opposite","回复取对方反隙"],["0","偶时隙"],["1","奇时隙"]]);
        field(f,"应答","sequence",[["manual","逐条确认"],["auto","本次自动编序"]]);
        field(f,"本台报告 dB","report").type="number";
        field(f,"无回应上限","limit").type="number";
        add(f,"small","报告由操作者填写。UTC 来源为电脑；真机阶段验证 GPS 授时和 PTT 提前量。");
    }
    const keys=add(work,"div","","keys");
    key(keys,"取消",()=>changePage(settingsBack));
    key(keys,settingsTab?"本台 / 音频":"时隙 / 应答",()=>{settingsTab=1-settingsTab;render()});
    key(keys,"示例值",()=>{Object.assign(draft,{call:"K1ABC",position:"demo",report:"-10"});render()});
    key(keys,"保存",()=>{
        draft.call=draft.call.toUpperCase();draft.grid=draft.grid.toUpperCase();
        if(draft.call && !/^(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{3,11}$/.test(draft.call)) return say("请输入标准业余电台呼号。");
        if(draft.position==="grid" && !gridCenter(draft.grid)) return say("请输入有效的四位或六位 Maidenhead 网格。");
        if(!Number.isInteger(+draft.hz)||+draft.hz<200||+draft.hz>2900) return say("TX 音频范围为 200–2900 Hz。");
        if(draft.report!=="" && (!/^[+-]?\d{1,2}$/.test(draft.report) || +draft.report < -50 || +draft.report>49)) return say("报告范围为 −50 到 +49 dB。");
        if(!Number.isInteger(+draft.limit)||+draft.limit<1||+draft.limit>10) return say("无回应上限为 1–10 次。");
        Object.assign(station,draft);say("本次会话设置已保存。");changePage(settingsBack);
    });
}
function renderTxMenu(work,bar) {
    bar.textContent=(ft4?"FT4":"FT8")+"　/　发射准备";clockBar(bar);
    const d=add(work,"div","","qso-info");
    add(d,"p",(station.call || "尚未设置呼号")+"　·　"+(localFix()?grid4(localFix()):"无定位"));
    add(d,"p",(station.sequence==="auto"?"自动编序":"逐条确认")+"　·　"+(station.audio==="fixed"?"固定音频":"回复跟频")+"　·　最多 "+station.limit+" 次无回应");
    add(d,"p","演练只更新屏幕。WAV 工具可独立导出音频文件。","last");
    const keys=add(work,"div","","keys");
    key(keys,"返回",()=>changePage("list"));key(keys,"TX 设置",()=>openSettings("txmenu"));
    key(keys,"呼叫 CQ",()=>newQso(true));key(keys,"WAV 工具",txForm);
}
function newQso(calling) {
    if(!station.call || !localFix() || station.report==="") {
        say("请先填写本台呼号、有效位置和本台报告，或点「示例值」体验。");
        return openSettings(calling?"txmenu":"detail");
    }
    if(!calling && selected.sender===station.call) return say("这条 CQ 来自本台。");
    if(!calling && receivedParity===null && station.parity==="opposite") {
        say("录音缺少可确认的起始时隙，请手动选择奇或偶。");return openSettings("detail");
    }
    const txParity=station.parity==="opposite"?(calling?0:1-receivedParity):Number(station.parity);
    if(!calling && receivedParity===txParity) {say("所选 TX 时隙与对台相同，请改为反隙。");return openSettings("detail");}
    qso={calling,peer:calling?null:selected.sender,hz:(!calling && station.audio==="follow")?selected.hz:Number(station.hz),
         txParity,step:0,waiting:false,armed:false,started:false,last:"",count:0,paused:false,done:false,
         auto:station.sequence==="auto",simulatePeer:true,lastSlot:slotId()};
    changePage("qso");
}
function proposed() {
    const q=qso, grid=grid4(localFix()), report=reportText(station.report);
    if(q.calling && q.step===0) return "CQ "+station.call+" "+grid;
    const extra=(q.calling?[null,report,"RR73"]:[grid,"R"+report,"73"])[q.step];
    return q.peer+" "+station.call+" "+extra;
}
function receiveQso(msg) {
    const q=qso;
    if(!q || !q.waiting || q.done || q.paused) return false;
    const [to,from,extra,...tail]=msg.split(" ");
    if(to!==station.call || (q.peer && q.peer!==from) || tail.length || from===station.call) return false;
    const valid=q.calling ? [!!gridCenter(extra) && extra!=="RR73",/^R[+-]\d{2}$/.test(extra),extra==="73"]
                          : [/^[+-]\d{2}$/.test(extra),["RR73","RRR"].includes(extra)];
    if(!valid[q.step]) return false;
    q.peer=from;q.last="示例 RX　"+msg;q.count=0;q.waiting=false;
    if(q.calling && q.step===2) q.done=true;
    else {q.step++;q.armed=q.auto;}
    return true;
}
function advanceQso(id) {
    const q=qso;
    if(!q || q.done || !q.started || q.paused) return;
    if(id%2===q.txParity) {
        if(!q.armed || q.waiting) return;
        q.last="演练 TX　"+proposed();q.armed=false;q.waiting=true;
        if(!q.calling && q.step===2) {q.done=true;q.waiting=false;}
    } else if(q.waiting) {
        const peer=q.peer || (station.call==="JA1ABC"?"DL1ABC":"JA1ABC");
        const extra=(q.calling?["PM95","R-08","73"]:["-08","RR73"])[q.step];
        if(q.simulatePeer && receiveQso(station.call+" "+peer+" "+extra)) return;
        q.last="示例 RX　无回应";q.count++;q.waiting=false;q.paused=q.count>=+station.limit;q.armed=q.auto && !q.paused;
    }
}
function tick() {
    if(page==="map") moveMapDot();
    if(page==="qso" && qso && qso.lastSlot!==slotId()) {
        const id=slotId(), gap=id-qso.lastSlot;qso.lastSlot=id;
        if((gap!==1 || nowMs()%slotMs()>500) && qso.started && !qso.done) {
            qso.paused=true;qso.armed=false;qso.last="错过时隙起点，演练停止";
        }
        else advanceQso(id);
        render();
    } else paintClock();
}
function renderQso(work,bar) {
    const q=qso;add(bar,"span",(ft4?"FT4":"FT8")+"　通联演练　"+(q.auto?"自动编序":"逐条确认"));clockBar(bar);
    const d=add(work,"div","","qso-info");
    add(d,"p",(q.peer||"CQ")+"　·　TX "+q.hz+" Hz　·　"+side(q.txParity)+"隙发　"+side(1-q.txParity)+"隙收");
    add(d,"div",q.last || "尚未发送演练报文","last");
    add(d,"b",q.done?"通联演练完成":q.paused?"演练已停止":q.waiting?"等待对台回应":proposed());
    const l=add(d,"label","示例对台回应　"), cb=add(l,"input","");l.style.display="block";cb.type="checkbox";cb.checked=q.simulatePeer;cb.onchange=()=>q.simulatePeer=cb.checked;
    const keys=add(work,"div","","keys");
    key(keys,q.done?"返回":"停止",()=>{stopSession();changePage("list")});
    key(keys,q.armed?"已排入"+side(q.txParity)+"隙":!q.started?"开始演练":"确认本条",
        q.done||q.paused||q.waiting||q.armed?null:()=>{q.started=true;q.armed=true;q.lastSlot=slotId();render()});
    key(keys,"快进一隙",q.done||q.paused||!q.started?null:()=>{rehearsalOffset+=slotMs()-nowMs()%slotMs();tick()});
}

function openMap(row) {
    mapBack=row?"detail":"list";mapIndex=row?rows.indexOf(row):-1;changePage("map");
}
function mapPoint([lat,lon]) {return [(lon+180)*355/360,(90-lat)*121/180];}
function greatCircle(a,b) {
    const rad=Math.PI/180;
    function vector([lat,lon]) {
        return [Math.cos(lat*rad)*Math.cos(lon*rad),Math.cos(lat*rad)*Math.sin(lon*rad),Math.sin(lat*rad)];
    }
    const u=vector(a),v=vector(b);
    const angle=Math.acos(Math.max(-1,Math.min(1,u.reduce((sum,x,i)=>sum+x*v[i],0))));
    if(angle<1e-6) return [a,b];
    if(Math.PI-angle<1e-6) return []; // No unique shortest arc.
    return Array.from({length:65},(_,i)=>{
        const t=i/64,p=u.map((x,n)=>x*Math.sin((1-t)*angle)+v[n]*Math.sin(t*angle));
        return [Math.atan2(p[2],Math.hypot(p[0],p[1]))/rad,Math.atan2(p[1],p[0])/rad];
    });
}
function moveMapDot() {
    const dot=document.querySelector(".mapdot");
    if(!dot) return;
    const points=dot.track, [x,y]=points[Math.floor(performance.now()/65)%points.length];
    dot.style.left=x/355*100+"%";dot.style.top=y/121*100+"%";
}
function renderMap(work,bar) {
    const overview=mapIndex<0;
    add(bar,"b",overview?"地图　/　本次收听":"地图　/　本时隙报文");clockBar(bar);
    const body=add(work,"div","","mapbody"),plot=add(body,"div","","mapplot"),canvas=add(plot,"canvas","");
    canvas.width=356;canvas.height=122;
    const ctx=canvas.getContext("2d"), site=localFix();
    const peers=[...heard].filter(([call])=>call!==station.call);
    const known=new Map(peers.filter(([,pos])=>pos));
    if(site && station.call) known.set(station.call,site);
    function dot(location,color,radius) {
        if(!location) return;
        const [x,y]=mapPoint(location);ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,radius,0,2*Math.PI);ctx.fill();
    }
    function arrow(a,b) {
        if(!a || !b) return;
        const points=greatCircle(a,b).map(mapPoint);
        if(!overview && points.length>2) {add(plot,"i","","mapdot").track=points;moveMapDot();}
        ctx.lineWidth=overview?1:1.5;ctx.strokeStyle=overview?"#8dcec9":"#ffcc68";ctx.beginPath();
        for(let i=0;i<points.length;i++) {
            const [x,y]=points[i];
            if(!i || Math.abs(points[i-1][0]-x)>178) ctx.moveTo(x,y);
            else ctx.lineTo(x,y);
        }
        ctx.stroke();
        if(overview) return;
        const mid=points[32],prev=points[31];
        if(!mid || Math.abs(mid[0]-prev[0])>178) return;
        ctx.save();ctx.translate(...mid);ctx.rotate(Math.atan2(mid[1]-prev[1],mid[0]-prev[0]));
        ctx.fillStyle="#ffcc68";ctx.beginPath();ctx.moveTo(4,0);ctx.lineTo(-3,-3);ctx.lineTo(-3,3);ctx.fill();ctx.restore();
    }
    const notes=add(body,"div","","mapnotes"),keys=add(work,"div","","keys");
    key(keys,"返回",()=>changePage(mapBack));
    if(overview) {
        const located=peers.filter(([,pos])=>pos);
        for(const [,pos] of located) arrow(pos,site);
        for(const [,pos] of located) dot(pos,"#ffcc68",2);
        dot(site,"#8de9af",3);
        add(notes,"b","听到 "+peers.length+" 台");
        add(notes,"div","已定位 "+located.length+" 台");
        add(notes,"div","位置未知 "+(peers.length-located.length)+" 台");
        add(notes,"div",site?"收听连线 → 本台":"本台位置未知");
        key(keys,"逐报查看",rows.length?()=>{mapIndex=0;render()}:null);
        return;
    }
    for(const pos of known.values()) dot(pos,"#9bd6d5",2);
    const r=rows[mapIndex],cq=r?.text.startsWith("CQ "),to=r?.text.split(" ")[0];
    const from=known.get(r?.sender),dest=cq?site:known.get(to);
    arrow(from,dest);dot(site,"#8de9af",3);dot(from,"#ffd06f",3);
    add(notes,"b",r?.sender||"无已知台站");
    add(notes,"div",cq?"→ 本台听到":to?"→ "+to:"");
    const km=distance(from,dest);
    add(notes,"div",km===null?"端点位置不全":"约 "+km+" km");
    add(notes,"div",cq?"收听连线":"报文收发方");
    add(notes,"div",known.size+" 个已知呼号位置");
    key(keys,"收听总览",()=>{mapIndex=-1;render()});
    key(keys,"上一报",mapIndex>0?()=>{mapIndex--;render()}:null);
    key(keys,"下一报",mapIndex+1<rows.length?()=>{mapIndex++;render()}:null);
}
