const $ = id => document.getElementById(id);
let ft4 = false, rows = [], page = "list", offset = 0, selected = null;
let importedFix = null;
const heard = new Map();
let heardSource="";
function remember(batch,source) {
    if(source!==heardSource) heard.clear();
    heardSource=source;
    for (const row of batch) {
        if (row.sender && (row.remote || !heard.has(row.sender))) heard.set(row.sender,row.remote);
    }
}
const samplesPerSlot = () => ft4 ? 90000 : 180000;
const say = text => $("notice").textContent = text;

function gridCenter(grid) {
    if (!/^[A-R]{2}[0-9]{2}([A-X]{2})?$/.test(grid)) return null;
    let lon = (grid.charCodeAt(0)-65)*20 + Number(grid[2])*2 - 180;
    let lat = (grid.charCodeAt(1)-65)*10 + Number(grid[3]) - 90;
    if (grid.length === 4) return [lat + 0.5, lon + 1];
    return [lat + (grid.charCodeAt(5)-64.5)/24, lon + (grid.charCodeAt(4)-64.5)/12];
}
function localFix() {
    if (station.position === "demo") return [35.5,139.5]; // J140 RMC replay fixture
    if (station.position === "grid") return gridCenter(station.grid);
    if (station.position === "gps") return importedFix;
    return null;
}
function parseFix(state) {
    if (state.position_valid !== true) return null;
    return [/^(\d{2})(\d{2})(\d{4})([NS])$/, /^(\d{3})(\d{2})(\d{4})([EW])$/].map((pattern,i)=>{
        const m=pattern.exec(state.coordinates?.[i]);
        if (!m || Number(m[2])>=60) throw Error("J140 坐标格式错误。");
        const degrees=Number(m[1])+(Number(m[2])+Number(m[3])/10000)/60;
        if(degrees>(i?180:90)) throw Error("坐标超出范围。");
        return /[SW]/.test(m[4])?-degrees:degrees;
    });
}
function grid4([lat,lon]) {
    const x = Math.min(lon+180,359.999999), y = Math.min(lat+90,179.999999);
    return String.fromCharCode(65+Math.floor(x/20),65+Math.floor(y/10)) +
        String(Math.floor(x/2)%10) + String(Math.floor(y)%10);
}
function distance(a,b) {
    if (!a || !b) return null;
    const rad = Math.PI/180;
    const h = Math.sin((b[0]-a[0])*rad/2)**2 +
        Math.cos(a[0]*rad)*Math.cos(b[0]*rad)*Math.sin((b[1]-a[1])*rad/2)**2;
    return Math.round(12742.0176*Math.asin(Math.sqrt(Math.min(1,h))));
}
function entity(call) {
    if (!call) return null;
    let id = countries.exact[call];
    if (id === undefined && /^[A-Z0-9]+$/.test(call)) {
        for (let n=call.length;n>0 && id===undefined;--n) id=countries.prefixes[call.slice(0,n)];
    }
    return countries.entities[id] || null;
}
function generate(text, hz) {
    const n = samplesPerSlot(), p = Module._malloc(2*n);
    try {
        if (!Module.ccall("tx_slot","number",["number","string","number","number","number"],
                [+ft4,text,hz,p,n])) throw Error("此报文无法原样编码，请检查呼号、网格或正文。");
        return Module.HEAP16.slice(p/2,p/2+n);
    } finally { Module._free(p); }
}
function decode(pcm) {
    const p = Module._malloc(2048);
    const result = [];
    try {
        Module._rx_begin(+ft4);
        for (let i=0; i<pcm.length; i+=1024) {
            const chunk=pcm.subarray(i,i+1024);
            Module.HEAP16.set(chunk,p/2);
            Module._rx_push(p,chunk.length);
        }
        const n=Module._rx_end();
        for (let i=0;i<n;++i) {
            const text=Module.UTF8ToString(Module._row_text(i)), start=Module._row_sender(i);
            const fields=start<0 ? [] : text.slice(start).split(" ");
            const grid=fields.at(-1);
            const db=Module._row_snr(i);
            result.push({text,hz:Module._row_hz(i),score:Module._row_score(i),snr:db===-128?null:db,
                         sender:fields[0],remote:fields.length>1 && grid!=="RR73" ? gridCenter(grid) : null});
        }
    } finally { Module._free(p); }
    return result.sort((a,b)=>a.hz-b.hz);
}
function loadDemo() {
    stopSession();
    receivedParity=0;
    const mix = new Int16Array(samplesPerSlot());
    const stations = [["CQ JA1ABC PM95",550],["CQ DL1ABC JO62",960],
                      ["F4ABC I4ABC RR73",1470],["CQ F4ABC JN18",1710],
                      ["CQ VE3ABC FN03",1970],["JA1ABC F4ABC -12",2190],
                      ["CQ EA1ABC IN73",2470],["CQ SP4ABC KO03",2750],
                      ["CQ VK2ABC QF56",740],["CQ G4ABC IO91",1210],["CQ W6ABC CM87",2590]];
    let seed=12345;
    for(let i=0;i<mix.length;i++){
        seed=(Math.imul(seed,1664525)+1013904223)>>>0;
        mix[i]=Math.round((seed/4294967296-.5)*3600);
    }
    for (const [j,[text,hz]] of stations.entries()) {
        const signal=generate(text,hz);
        for (let i=0;i<mix.length;++i) mix[i]+=Math.trunc(signal[i]/(12+j*3));
    }
    rows=decode(mix); remember(rows,"demo"); offset=0; page="list"; selected=null;
    say("已解码 "+stations.length+" 路混合的示例音频，共收到 "+rows.length+" 条。"); render();
}
function readWave(buffer) {
    const v=new DataView(buffer);
    const tag=i=>String.fromCharCode(...new Uint8Array(buffer,i,4));
    if (v.byteLength<44 || tag(0)!=="RIFF" || tag(8)!=="WAVE") throw Error("请选择 PCM WAV 文件。");
    let fmtOK=false, data=null;
    for (let i=12;i+8<=v.byteLength;) {
        const n=v.getUint32(i+4,true), start=i+8;
        if (n>v.byteLength-start) throw Error("WAV 数据不完整。");
        if (tag(i)==="fmt " && n>=16) fmtOK=v.getUint16(start,true)===1 &&
            v.getUint16(start+2,true)===1 && v.getUint32(start+4,true)===12000 &&
            v.getUint16(start+12,true)===2 && v.getUint16(start+14,true)===16;
        if (tag(i)==="data") data=[start,n];
        i=start+n+(n%2);
    }
    if (!fmtOK || !data || data[1]%2) throw Error("需要 12 kHz、16 位、单声道 PCM。");
    if (!data[1] || data[1]/2>samplesPerSlot()) throw Error("请选择当前模式的单个时隙。");
    return new Int16Array(buffer,data[0],data[1]/2);
}
function wave(pcm) {
    const buffer=new ArrayBuffer(44+2*pcm.length), v=new DataView(buffer);
    const tag=(i,s)=>[...s].forEach((c,j)=>v.setUint8(i+j,c.charCodeAt(0)));
    tag(0,"RIFF"); v.setUint32(4,buffer.byteLength-8,true);tag(8,"WAVE");tag(12,"fmt ");
    v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);
    v.setUint32(24,12000,true);v.setUint32(28,24000,true);v.setUint16(32,2,true);
    v.setUint16(34,16,true);tag(36,"data");v.setUint32(40,pcm.byteLength,true);
    new Int16Array(buffer,44).set(pcm);return buffer;
}
function add(parent,tag,content,cls="") {
    const el=document.createElement(tag);el.className=cls;el.textContent=content;parent.append(el);return el;
}
function key(parent,label,action) {
    const b=add(parent,"button",label);b.disabled=!action;if(action) b.onclick=action;return b;
}
function preset() {stopSession();heard.clear();page="preset"; selected=null; rows=[];offset=0;receivedParity=null; render();}
function txForm() {
    page="tx";render();
    const me=station.call, site=localFix();
    if (me && site) $("txtext").value=(selected?.sender || "CQ")+" "+me+" "+grid4(site);
    $("txtext").focus();
}
function saveAudio() {
    try {
        const msg=$("txtext").value.trim().toUpperCase(), hz=Number($("txhz").value);
        if (!Number.isInteger(hz) || hz<200 || hz>2900) throw Error("音频基频范围为 200–2900 Hz。");
        const pcm=generate(msg,hz), link=document.createElement("a");
        const url=URL.createObjectURL(new Blob([wave(pcm)],{type:"audio/wav"}));
        link.href=url;link.download=(ft4?"FT4-":"FT8-")+msg.replace(/[^0-9A-Z-]/g,"_")+".wav";link.click();
        setTimeout(()=>URL.revokeObjectURL(url),1000);say("已导出 "+msg+"，基频 "+hz+" Hz。");
        page="list";render();
    } catch(e) {say(e.message);}
}
function render() {
    const work=$("work"); work.replaceChildren();
    document.querySelector(".radiohead").classList.toggle("ft4",ft4);
    manageClock();
    const half=page==="list" && $("layout").value==="half";
    $("lcd").classList.toggle("half",half);
    work.classList.toggle("activity",page==="list");
    const dense=$("layout").value==="dense";
    work.classList.toggle("dense",dense && page==="list");
    work.classList.toggle("stockhome",page==="home");
    if(page==="home") return;
    const bar=add(work,"div","","bar"), per=half?4:dense?10:7;
    if (page==="settings") return renderSettings(work,bar);
    if (page==="txmenu") return renderTxMenu(work,bar);
    if (page==="qso") return renderQso(work,bar);
    if (page==="map") return renderMap(work,bar);
    if (page==="preset" || page==="loaded") {
        bar.textContent="MENU  /  PRESET  /  FT8";
        const p=add(work,"div","","preset");
        if (page==="loaded") add(p,"span","USB-D 设置已加载（模拟）");
        else key(p,"Load preset · 加载设置",()=>{page="loaded";render()});
        for (const m of ["FT8","FT4"]) key(p,m+" · 机内操作",()=>{ft4=m==="FT4";loadDemo()});
        return;
    }
    if (page==="detail") {
        bar.textContent="STATION  /  "+(selected.sender || "MESSAGE");
        const d=add(work,"div","","detail"), c=entity(selected.sender), km=distance(localFix(),selected.remote);
        add(d,"b",selected.text); add(d,"p",(c?c[0]:"未知 DXCC 实体")+"　·　"+(km===null?"距离未知":"约 "+km+" km"));
        add(d,"p","AF "+selected.hz+" Hz　·　SNR "+(selected.snr===null?"未知":selected.snr+" dB")+"　·　"+(receivedParity===null?"录音时隙未知":side(receivedParity)+"隙收到"));
        const keys=add(work,"div","","keys"); key(keys,"返回",()=>{page="list";render()});
        key(keys,"地图",()=>openMap(selected));
        key(keys,"回复此 CQ",/^CQ /.test(selected.text) && /^[A-Z0-9/]+$/.test(selected.sender)?()=>newQso(false):null); return;
    }
    if (page==="tx") {
        bar.textContent="TX  /  报文预览";const d=add(work,"div","","detail");
        const t=add(d,"input","");t.id="txtext";t.maxLength=34;t.style.width="100%";t.placeholder="输入完整报文";t.setAttribute("aria-label","待发报文");
        const l=add(d,"label","AF (Hz)　"), h=add(l,"input","");h.id="txhz";h.type="number";h.min=200;h.max=2900;h.value=selected?.hz || 1000;
        const keys=add(work,"div","","keys");key(keys,"取消",()=>{page="list";render()});key(keys,"导出 TX WAV",saveAudio);return;
    }
    offset=Math.min(offset,Math.max(0,Math.floor((rows.length-1)/per)*per));
    const range=rows.length ? (offset+1)+"–"+Math.min(rows.length,offset+per)+" / "+rows.length : "0";
    add(bar,"span",(ft4?"FT4 ":"FT8 ")+range);clockBar(bar);
    for(const label of ["dB","Hz","≈ km"]) add(bar,"span",label,"unit");
    const list=add(work,"div","","records");
    for(const r of rows.slice(offset,offset+per)) {
        const b=add(list,"button","","record"), c=entity(r.sender), flag=c && countries.flags[c[1]];
        if(flag){const el=add(b,"img","");el.src=flag;el.alt=c[0];}
        else add(b,"span",c?.[1] || "–","region");
        add(b,"span",r.text,"message"+(r.text.startsWith("CQ ")?" cq":""));
        add(b,"span",r.snr===null?"—":r.snr>0?"+"+r.snr:r.snr,"snr");
        add(b,"span",r.hz,"af");add(b,"span",distance(localFix(),r.remote)??"—","km");
        b.onclick=()=>{selected=r;page="detail";render()};
    }
    if (!rows.length) add(list,"div","本时隙无解码","detail");
    const keys=add(work,"div","","keys");key(keys,"PRESET",preset);
    key(keys,"◀",offset>0?()=>{offset-=per;render()}:null);
    key(keys,"▶",offset+per<rows.length?()=>{offset+=per;render()}:null);
    key(keys,dense?"7 行":"10 行",()=>{
        $("layout").value=dense?"large":"dense";offset=0;render();
    });
    key(keys,"地图",()=>openMap(null));
    key(keys,"TX…",()=>{selected=null;page="txmenu";render()});
}
function startPanel() {
    $("presetKey").onclick=preset;
    $("exitKey").onclick=leaveStation;
    document.addEventListener("keydown",e=>{if(e.key==="Escape"){e.preventDefault();leaveStation();}});
    $("layout").onchange=()=>{offset=0;render()};
    $("gpsFile").onchange=async()=>{
        const f=$("gpsFile").files[0]; if(!f) return;
        const request=sessionRevision;
        try {
            if(f.size>100000) throw Error("请选择单次 GPS 状态 JSON。");
            const raw=await f.text();
            if(request!==sessionRevision || page!=="settings") return;
            importedFix=parseFix(JSON.parse(raw));
            say(importedFix?"已读取 J140 定位快照。":"该快照的定位已失效。");
        } catch(e) {importedFix=null;say(e.message);}
        $("gpsFile").value="";
        if(page==="settings") {draft.position="gps";render();}
    };
    $("demo").onclick=loadDemo;
    $("open").onclick=()=>$("file").click();
    $("file").onchange=async()=>{
        const f=$("file").files[0];if (!f) return;
        const request=++sessionRevision;
        try {
            if (f.size>2e6) throw Error("请选择单时隙 WAV。");
            const raw=await f.arrayBuffer();
            if(request!==sessionRevision) return;
            const incoming=decode(readWave(raw));
            stopSession();rows=incoming;remember(rows,"wav");selected=null;offset=0;page="list";
            receivedParity=fileParity(f.name);
            say(f.name+" · 收到 "+rows.length+" 条报文。");render();
        } catch(e) {say(e.message);}
        $("file").value="";
    };
    loadDemo();
}
