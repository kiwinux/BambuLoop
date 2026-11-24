// Runs the actual Pages UI in a disposable Chromium profile. No Python or npm packages.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { crc32, inflateRawSync } from "node:zlib";
import { preview, prefix } from "../tools/preview.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const scratchRoot = path.join(root, ".dev-notes");
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn, label, timeout = 90000) {
  const end = Date.now() + timeout;
  let last;
  while (Date.now() < end) {
    try { const value = await fn(); if (value) return value; } catch (error) { last = error; }
    await delay(120);
  }
  throw new Error("Timed out: " + label + (last ? ": " + last.message : ""));
}

function fixture(layers, height = 10) {
  return [
    "; HEADER_BLOCK_START", "; max_z_height: " + height, "; total layer number: " + layers,
    "; HEADER_BLOCK_END", "; CONFIG_BLOCK_START", "; printer_model = Bambu Lab H2S",
    "; curr_bed_type = High Temp Plate", "; CONFIG_BLOCK_END", "G28", ";===== machine: H2S =====",
    "M972 S41 P0 T5000 ; trash can", "M1002 judge_flag build_plate_detect_flag", "M622 S1",
    "M972 S19 P0 C0 ; heatbed detection", "M972 S31 P0 T5000", "M972 S34 P0 T5000", "M623",
    "G29", ";===== auto extrude cali end =====",
    "M83", "G1 E45 F600", "G1 E-3 F1800", "G150.2", "G150.1", "G91", "G1 Y-16 F12000", "G90",
    ";===== wipe right nozzle start =====", "G1 X10 Y10 Z1",
    ...Array.from({length:layers}, (_,i) => "; CHANGE_LAYER\nM73 L" + (i+1) + "\nG1 X10 Y10 Z1"),
    "; filament end gcode", "M84"
  ].join("\n");
}

// Small archive fixture with independently written ZIP headers.
function archive(entries) {
  const local=[], central=[];
  let position=0;
  for (const [name,value] of Object.entries(entries)) {
    const n=Buffer.from(name), data=Buffer.from(value), header=Buffer.alloc(30);
    header.writeUInt32LE(0x04034b50); header.writeUInt16LE(20,4);
    header.writeUInt32LE(crc32(data),14); header.writeUInt32LE(data.length,18);
    header.writeUInt32LE(data.length,22); header.writeUInt16LE(n.length,26);
    const entry=Buffer.alloc(46); entry.writeUInt32LE(0x02014b50); entry.writeUInt16LE(20,4);
    header.copy(entry,6,4,28); entry.writeUInt32LE(position,42);
    local.push(header,n,data); central.push(entry,n); position+=header.length+n.length+data.length;
  }
  const cd=Buffer.concat(central), end=Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50); end.writeUInt16LE(central.length/2,8); end.writeUInt16LE(central.length/2,10);
  end.writeUInt32LE(cd.length,12); end.writeUInt32LE(position,16);
  return Buffer.concat([...local,cd,end]);
}
function members(zip) {
  const end=zip.lastIndexOf(Buffer.from([0x50,0x4b,0x05,0x06])), result=new Map();
  for (let p=zip.readUInt32LE(end+16); p<end;) {
    assert.equal(zip.readUInt32LE(p),0x02014b50);
    const len=zip.readUInt16LE(p+28), name=zip.subarray(p+46,p+46+len).toString();
    const off=zip.readUInt32LE(p+42), start=off+30+zip.readUInt16LE(off+26)+zip.readUInt16LE(off+28);
    const bytes=zip.subarray(start,start+zip.readUInt32LE(p+20));
    result.set(name,zip.readUInt16LE(p+10)===8 ? inflateRawSync(bytes) : bytes);
    p+=46+len+zip.readUInt16LE(p+30)+zip.readUInt16LE(p+32);
  }
  return result;
}

async function findBrowser() {
  for (const item of [process.env.BAMBULOOP_CHROME,
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/usr/bin/chromium", "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].filter(Boolean)) {
    if (await fs.stat(item).then(v=>v.isFile()).catch(()=>false)) return item;
  }
  throw new Error("Set BAMBULOOP_CHROME to a Chromium executable.");
}

await fs.mkdir(scratchRoot,{recursive:true});
const scratch=await fs.mkdtemp(path.join(scratchRoot,"pages-qa-"));
const profile=path.join(scratch,"profile"), downloads=path.join(scratch,"downloads"), temp=path.join(scratch,"temp");
await Promise.all([profile,downloads,temp].map(p=>fs.mkdir(p)));
const server=await preview(0);
const origin="http://127.0.0.1:" + server.address().port;
const served=[];
server.on("request",req=>served.push([req.method,req.url]));
const proxy=createServer((_req,res)=>res.writeHead(403).end());
proxy.on("connect",(_req,socket)=>socket.destroy());
await new Promise(resolve=>proxy.listen(0,"127.0.0.1",resolve));
let child, ws, evaluate, closed;
const errors=[];
try {
  const binary=await findBrowser();
  child=spawn(binary,["--headless=new","--remote-debugging-port=0","--remote-debugging-address=127.0.0.1",
    "--user-data-dir="+profile,"--disk-cache-dir="+path.join(scratch,"cache"),
    "--no-first-run","--no-default-browser-check","--disable-extensions","--disable-sync",
    "--disable-background-networking","--disable-component-update","--disable-breakpad","--disable-crash-reporter",
    "--proxy-server=http://127.0.0.1:"+proxy.address().port,
    "--proxy-bypass-list=localhost;127.0.0.1", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost", "about:blank"],
    {windowsHide:true,stdio:"ignore",env:{...process.env,TEMP:temp,TMP:temp,TMPDIR:temp}});
  closed=new Promise((resolve,reject)=>{child.once("exit",resolve);child.once("error",reject);});
  const port=await until(async()=>Number((await fs.readFile(path.join(profile,"DevToolsActivePort"),"utf8")).split("\n")[0]),"Chrome port",25000);
  const tabs=await (await fetch("http://127.0.0.1:"+port+"/json/list")).json();
  ws=new WebSocket(tabs.find(t=>t.type==="page").webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  let seq=0;
  const waiting=new Map(), requests=[];
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id && waiting.has(msg.id)) {
      const cb=waiting.get(msg.id);waiting.delete(msg.id);
      if(msg.error) cb.reject(new Error(msg.error.message)); else cb.resolve(msg.result);
    } else if(msg.method==="Runtime.exceptionThrown") {
      errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
    } else if(msg.method==="Network.requestWillBeSent") {
      requests.push(msg.params.request.url);
    }
  };
  const cdp=(method,params={})=>new Promise((resolve,reject)=>{
    const id=++seq;waiting.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));
  });
  evaluate=async(expression)=>{
    const v=await cdp("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true,userGesture:true});
    if(v.exceptionDetails) throw new Error(v.exceptionDetails.exception?.description||v.exceptionDetails.text);
    return v.result.value;
  };
  const wait=(expression,label,timeout)=>until(()=>evaluate(expression),label,timeout);
  await Promise.all([cdp("Page.enable"),cdp("Runtime.enable"),cdp("Network.enable")]);
  await cdp("Browser.setDownloadBehavior",{behavior:"allow",downloadPath:downloads});
  await cdp("Page.addScriptToEvaluateOnNewDocument",{source:
    "const send = Worker.prototype.postMessage; Worker.prototype.postMessage = function(msg,...rest) {" +
    "if(msg.action==='generate') window.qaGeneration=structuredClone(msg.data); return send.call(this,msg,...rest); }"
  });
  async function nativeParity(source, result) {
    if (!process.env.BAMBULOOP_REFERENCE_PYTHON) return;
    const payload = await evaluate("window.qaGeneration");
    const check = spawnSync(process.env.BAMBULOOP_REFERENCE_PYTHON, ["-I","-B","-X","utf8",path.join(root,"tests","compare_engine.py")], {
      windowsHide:true, cwd:root, encoding:"utf8", input: JSON.stringify({source,result,payload}),
      env:{...process.env,TEMP:temp,TMP:temp,TMPDIR:temp}
    });
    if (check.status !== 0) throw new Error(check.stderr || "Native comparison failed.");
    console.log(check.stdout.trim());
  }
  const direct = await fetch(origin+prefix);
  const staticPage=await direct.text();
  assert.equal(direct.status,200);
  assert.match(staticPage, /<html lang="en">/);
  assert.match(staticPage, /<title\b[^>]*>BambuLoop — Repeat Printing for Bambu Lab H2S<\/title>/);
  assert.match(staticPage, />Choose files or drop them here</);
  await cdp("Emulation.setDeviceMetricsOverride",{width:1200,height:800,deviceScaleFactor:1,mobile:false});
  const nav = await cdp("Page.navigate",{url:origin+prefix});
  if (nav.errorText) throw new Error("Chrome navigation: "+nav.errorText);
  await wait("!!document.querySelector('#fileInput')","static HTML",10000);
  await wait("document.querySelector('#sound_print_done')?.options.length > 1","page and presets",15000);
  const languages = {
    en: {title:"BambuLoop — Repeat Printing for Bambu Lab H2S", files:"Choose files or drop them here",
         toggle:"한국어", preview:"Preview in browser", placeholder:"e.g. My Melody 1"},
    ko: {title:"BambuLoop — Bambu Lab H2S 자동 반복 인쇄", files:"파일을 선택하거나 여기에 놓으세요",
         toggle:"EN", preview:"브라우저에서 미리듣기", placeholder:"예: 내 멜로디 1"}
  };
  async function checkLocale(lang) {
    await wait("document.documentElement.lang==="+JSON.stringify(lang)+" && document.title==="+JSON.stringify(languages[lang].title),"locale "+lang,10000);
    const ui = await evaluate("({title:document.title,files:document.querySelector('[data-i18n=choose_files]').textContent,toggle:document.getElementById('langToggle').textContent.trim(),preview:document.querySelector('.sound-preview-btn').title,placeholder:document.getElementById('cmName').placeholder})");
    assert.deepEqual(ui,languages[lang]);
  }
  async function revisit(lang) {
    await evaluate("window.qaBeforeReload=true");
    await cdp("Page.reload",{ignoreCache:true});
    await wait("window.qaBeforeReload===undefined && document.querySelector('#sound_print_done')?.options.length>1","new page ready",15000);
    await checkLocale(lang);
  }
  assert.equal(await evaluate("localStorage.getItem('bambuloop_lang')"),null);
  await checkLocale("en");
  const links = await evaluate("(()=>{const project=document.getElementById('projectLink'),box=document.getElementById('contributionNotice'), rect=box.getBoundingClientRect();return {repo:project.href,icon:!!project.querySelector('svg path'),roadmap:document.getElementById('roadmapLink').href,guide:box.querySelector('[data-i18n=contribution_guide]').href,shown:!box.hidden,title:document.getElementById('contributionHeading').textContent,nearCorner:rect.left<50 && rect.top>=0 && rect.bottom<=innerHeight && innerHeight-rect.bottom<50}})()");
  assert.deepEqual(links,{repo:"https://github.com/kiwinux/BambuLoop",icon:true,roadmap:"https://github.com/kiwinux/BambuLoop#roadmap--contributing",guide:"https://github.com/kiwinux/BambuLoop/blob/main/CONTRIBUTING.md",shown:true,title:"Contribute to BambuLoop",nearCorner:true});
  await evaluate("localStorage.setItem('bambuloop_lang','unknown'); localStorage.setItem('bambuloop_contribution_dismissed','1')");
  await revisit("en");
  assert.equal(await evaluate("document.getElementById('contributionNotice').hidden"), false);
  await evaluate("localStorage.removeItem('bambuloop_contribution_dismissed')");
  await evaluate("document.getElementById('langToggle').click()");
  await checkLocale("ko");
  await revisit("ko");
  assert.match(await evaluate("document.getElementById('contributionHeading').textContent"), /개발에 참여/);
  assert.match(await evaluate("decodeURI(document.getElementById('roadmapLink').href)"), /README\.ko\.md#로드맵--기여$/);
  await cdp("Emulation.setDeviceMetricsOverride",{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert.ok(await evaluate("(()=>{const b=document.getElementById('contributionNotice'),r=b.getBoundingClientRect();return !b.hidden && r.left>=0 && r.left<24 && r.right<=document.documentElement.clientWidth && r.top>=0 && Math.abs(innerHeight-r.bottom)<25})()"));
  await cdp("Emulation.setDeviceMetricsOverride",{width:1200,height:800,deviceScaleFactor:1,mobile:false});
  await evaluate("document.getElementById('dismissContribution').click()");
  assert.ok(await evaluate("document.getElementById('contributionNotice').hidden"));
  await evaluate("document.getElementById('langToggle').click()");
  await checkLocale("en");
  assert.equal(await evaluate("document.getElementById('contributionNotice').hidden"), true);
  assert.equal(await evaluate("localStorage.getItem('bambuloop_contribution_dismissed')"), null);
  await revisit("en");
  assert.equal(await evaluate("document.getElementById('contributionNotice').hidden"), false);
  await evaluate("document.getElementById('langToggle').click()");
  await checkLocale("ko");
  const controls=await evaluate(`(() => {
    const ids=['fileInput','part_fan_enabled','aux_fan_enabled','chamber_fan_enabled'];
    const focus=ids.map(id=>{const el=document.getElementById(id);el.focus();return document.activeElement===el;});
    const fields=['back_overhang_mm','front_overhang_mm','eject_z_offset','eject_method'];
    const values=fields.map(id=>document.getElementById(id).value);
    ['0','0','0','bottom_only'].forEach((v,i)=>document.getElementById(fields[i]).value=v);
    document.getElementById('eject_z_offset').dispatchEvent(new Event('input'));
    const zeros=[...document.querySelectorAll('#sweepZBar text')].every(el=>el.textContent==='0.0');
    const edges=document.getElementById('sweepTopSvg').textContent;
    fields.forEach((id,i)=>document.getElementById(id).value=values[i]);
    document.getElementById('eject_z_offset').dispatchEvent(new Event('input'));
    localStorage.setItem('farmloop_custom_melodies',JSON.stringify({'Study <A> & B':[[60,30]]}));
    document.getElementById('customMelodyBtn').click();
    const melody=document.querySelector('.melody-name');
    const literal=melody?.textContent==='Study <A> & B' && !melody.childElementCount;
    document.getElementById('cmCancel').click();
    return {focus,zeros,edges,literal};
  })()`);
  assert.ok(controls.focus.every(Boolean) && controls.zeros && controls.literal,JSON.stringify(controls));
  assert.match(controls.edges,/Y=320/);
  assert.match(controls.edges,/Y=0/);
  const batch=await evaluate(`(async()=>{
    const {requestJob}=await import('./assets/client.mjs');
    const success=new File([${JSON.stringify(fixture(1))}],'one.gcode');
    const res=await requestJob('import',{}, {files:[success,{name:'unreadable.gcode',size:1}]});
    for(const f of res.data.files) await requestJob('delete_upload',{stored_name:f.stored_name});
    return [res.data.files.length,res.data.errors.length];
  })()`);
  assert.deepEqual(batch,[1,1]);
  const data=archive({"Metadata/plate_2.gcode":fixture(3),"metadata/PLATE_10.GCODE":fixture(1),
    "Metadata/plate_2.json":'{"filament_ids":[2],"source":2,"bed_type":"textured_plate"}',"metadata/PLATE_10.JSON":'{"filament_ids":[5],"source":10,"bed_type":"hot_plate"}',
    "Metadata/project_settings.config":'{"curr_bed_type":"High Temp Plate"}',
    "Metadata/plate_2.png":"thumbnail 2","metadata/PLATE_10.PNG":"thumbnail 10", "metadata/PLATE_10.GCODE.MD5":"OLD", "Extras/plate_preview.gcode.md5":"preserved checksum","3D/model.bin":"preserved"});
  const input=path.join(scratch,"two plates.gcode.3mf");
  await fs.writeFile(input,data);
  async function choose(files) {
    const {root:doc}=await cdp("DOM.getDocument");
    const {nodeId}=await cdp("DOM.querySelector",{nodeId:doc.nodeId,selector:"#fileInput"});
    await cdp("DOM.setFileInputFiles",{nodeId,files});
  }
  assert.match(await evaluate("document.querySelector('footer [data-i18n=privacy_files]').textContent"), /외부 서버로 전송되지 않습니다/);
  console.log("Static page and local presets loaded.");
  await choose([input]);
  await wait("document.querySelectorAll('.job-item').length === 2","3MF import");
  await evaluate("document.getElementById('generateBtn').click()");
  await wait("document.querySelector('#result.show #downloadLink')?.download.endsWith('.3mf')","combined result");
  console.log("3MF imported and generated in the worker.");
  const output=await evaluate("document.getElementById('downloadLink').download");
  await evaluate("document.getElementById('downloadLink').click()");
  const bytes=await until(()=>fs.readFile(path.join(downloads,output)),"download");
  await nativeParity(input,path.join(downloads,output));
  const zip=members(bytes), gcode=zip.get("Metadata/plate_2.gcode");
  assert.deepEqual(gcode,zip.get("metadata/PLATE_10.GCODE"));
  assert.equal(zip.get("Extras/plate_preview.gcode.md5").toString(),"preserved checksum");
  const byKey=new Map([...zip].map(([name,bytes])=>[name.toLowerCase(),bytes]));
  assert.equal(zip.get("3D/model.bin").toString(),"preserved");
  for(const n of [2,10]) {
    assert.equal(byKey.get("metadata/plate_"+n+".gcode.md5").toString(),createHash("md5").update(gcode).digest("hex").toUpperCase());
    assert.deepEqual(JSON.parse(byKey.get("metadata/plate_"+n+".json")), {filament_ids:[2,5],source:2,bed_type:"textured_plate"});
    assert.equal(byKey.get("metadata/plate_"+n+".png").toString(),"thumbnail 2");
  }
  assert.equal(await evaluate("document.getElementById('verify_build_plate').checked"), true);
  assert.match(await evaluate("document.getElementById('plateCheckSource').textContent"), /plate_2.*Textured PEI Plate/);
  assert.equal(JSON.parse(zip.get("Metadata/project_settings.config")).curr_bed_type,"Textured PEI Plate");
  function checks(text) {
    return text.split(/\r?\n/).map(line=>line.split(";")[0].trim()).filter(line=>/^M972\s+S19\b/i.test(line)).length;
  }
  assert.equal(checks(gcode.toString()),1);
  const text=gcode.toString(), reset=text.split("; [reset sequence]")[1].split("; ----- nozzle load line")[0];
  assert.match(text,/; total layer number: 4\b/);
  assert.equal((reset.match(/^G1 Y-16\b/gm)||[]).length,1);
  assert.equal((reset.match(/^\s*G150\.1\b/gm)||[]).length,1);
  await evaluate("const m=document.getElementById('safetyMargin'); m.value='0';document.getElementById('safetyRecheck').click()");
  await wait("document.getElementById('sPhysical').textContent.includes('0mm') && document.getElementById('sHeader').textContent.includes('plate_2.gcode')","downloaded 3MF recheck");
  await evaluate("document.getElementById('verify_build_plate').click()");
  assert.match(await evaluate("document.getElementById('resultPlateCheck').textContent"),/1회/);
  assert.match(await evaluate("document.getElementById('plateCheckSource').textContent"),/생략/);
  await evaluate("document.getElementById('generateBtn').click()");
  await wait("document.querySelector('#result.show #downloadLink')?.download.endsWith('.3mf')","without plate identification");
  const without=await evaluate("document.getElementById('downloadLink').download");
  assert.notEqual(without,output);
  await evaluate("document.getElementById('downloadLink').click()");
  const noCheck=members(await until(()=>fs.readFile(path.join(downloads,without)),"unchecked download"));
  for (const n of ["Metadata/plate_2.gcode","metadata/PLATE_10.GCODE"]) {
    assert.equal(checks(noCheck.get(n).toString()),0);
    assert.match(noCheck.get(n).toString(),/^M972 S41 P0 T5000/m);
    assert.match(noCheck.get(n).toString(),/^G29$/m);
  }
  assert.equal(JSON.parse(noCheck.get("Metadata/plate_2.json")).bed_type,"textured_plate");
  assert.match(await evaluate("document.getElementById('resultPlateCheck').textContent"),/생략/);
  await nativeParity(input,path.join(downloads,without));
  await evaluate("document.getElementById('langToggle').click()");
  await wait("document.documentElement.lang === 'en' && document.querySelector('[data-i18n=cooling_wait_hint]').textContent.includes('default 5')","English labels");
  assert.match(await evaluate("document.querySelector('footer [data-i18n=privacy_files]').textContent"), /never sent to an external server/);
  await evaluate("document.getElementById('dryRunBtn').click();document.getElementById('drGenerate').click()");
  await wait("document.querySelector('#result.show #downloadLink')?.download.startsWith('DRYRUN')","dry run");
  assert.ok(!(await evaluate("document.getElementById('downloadLink').textContent")).includes("3mf"));
  const dryText=await evaluate("fetch(document.getElementById('downloadLink').href).then(r=>r.text())");
  assert.equal(checks(dryText),0);
  await evaluate("document.getElementById('langToggle').click()");
  await checkLocale("ko");
  assert.match(await evaluate("document.getElementById('drGenerate').textContent"), /생성/);
  assert.equal(await evaluate("document.querySelector('[data-i18n=total_prints]').textContent"), "총 인쇄");
  await evaluate("document.getElementById('langToggle').click()");
  await checkLocale("en");

  await evaluate("document.getElementById('verify_build_plate').click();document.querySelector('.job-item [data-act=del]').click()");
  await wait("document.querySelectorAll('.job-item').length===1 && document.getElementById('plateCheckSource').textContent.includes('plate_10')", "switch first source plate");
  assert.match(await evaluate("document.getElementById('plateCheckSource').textContent"), /High Temp Plate/);
  await evaluate("document.getElementById('dryRunBtn').click();document.getElementById('dr_cycles').value='3';document.getElementById('drGenerate').click()");
  await wait("document.querySelector('#result.show #downloadLink')?.download.startsWith('DRYRUN')","multi-cycle source dry run");
  assert.equal(checks(await evaluate("fetch(document.getElementById('downloadLink').href).then(r=>r.text())")),1);
  await evaluate("document.getElementById('generateBtn').click()");
  await wait("document.querySelector('#result.show #downloadLink')?.download.endsWith('.3mf')","new first-plate archive");
  const switched=await evaluate("document.getElementById('downloadLink').download");
  await evaluate("document.getElementById('downloadLink').click()");
  const secondZip=members(await until(()=>fs.readFile(path.join(downloads,switched)),"second source download"));
  assert.equal(JSON.parse(secondZip.get("Metadata/plate_2.json")).bed_type,"hot_plate");
  assert.equal(JSON.parse(secondZip.get("metadata/PLATE_10.JSON")).source,10);
  assert.equal(checks(secondZip.get("metadata/PLATE_10.GCODE").toString()),1);
  await evaluate("document.getElementById('safetyRecheck').click()");
  await wait("document.getElementById('sHeader').textContent.includes('PLATE_10.GCODE')","recheck originating 3MF entry");
  await nativeParity(input,path.join(downloads,switched));
  await evaluate("document.getElementById('soundCatalogBtn').click()");
  await until(async()=>(await fs.readdir(downloads)).some(f=>/^sound_catalog.*\.gcode$/.test(f)),"sound catalog");
  await evaluate("document.getElementById('resetBtn').click();document.getElementById('alertModalOk').click()");
  await wait("document.querySelectorAll('.job-item').length === 0 && !document.querySelector('#result.show')","reset");
  const tall=path.join(scratch,"tall.gcode");
  await fs.writeFile(tall,fixture(1,42));
  await choose([tall]); await wait("document.querySelectorAll('.job-item').length === 1","plain G-code");
  await evaluate("document.getElementById('eject_method').value='bottom_only';document.getElementById('generateBtn').click()");
  await wait("document.getElementById('alertModal').style.display === 'flex'","42 mm block");
  assert.match(await evaluate("document.getElementById('alertModalBody').textContent"),/42/);
  await evaluate("document.getElementById('alertModalOk').click()");
  await wait("!document.getElementById('generateBtn').disabled","clearance dialog closed",10000);
  await evaluate("document.getElementById('eject_method').value='none';document.getElementById('generateBtn').click()");
  await wait("document.querySelector('#result.show #downloadLink')?.download.endsWith('.gcode')","plain G-code download");
  assert.equal((await evaluate("document.getElementById('downloadLink').href")).startsWith("blob:"),true);
  const sampleFlag = process.argv.indexOf("--sample");
  if (sampleFlag !== -1) {
    const sample = await fs.realpath(process.argv[sampleFlag+1]);
    await evaluate("document.getElementById('resetBtn').click();document.getElementById('alertModalOk').click()");
    await wait("document.querySelectorAll('.job-item').length === 0","reset before archived sample");
    await choose([sample]);
    await wait("document.querySelectorAll('.job-item').length >= 2","archived plates",150000);
    await evaluate(`
      const names = [...document.querySelectorAll('.job-name')].map(el=>el.textContent);
      const keep = names[1];
      while (document.querySelectorAll('.job-item').length > 1) {
        const row=[...document.querySelectorAll('.job-item')].find(el=>el.querySelector('.job-name').textContent!==keep);
        row.querySelector('[data-act=del]').click();
      }
      const count = document.querySelector('.job-item input'); count.value=2; count.dispatchEvent(new Event('change'));
      document.getElementById('eject_method').value='edge_to_center';
      document.getElementById('generateBtn').click();
    `);
    await wait("document.querySelector('#result.show #downloadLink')?.download.endsWith('.3mf')","archived 3MF generation",240000);
    const filename=await evaluate("document.getElementById('downloadLink').download");
    await evaluate("document.getElementById('downloadLink').click()");
    await until(()=>fs.stat(path.join(downloads,filename)),"archived file download");
    await nativeParity(sample,path.join(downloads,filename));
    console.log("Archived sample: selected second plate, 2 repeats, downloaded",filename);
  }
  await cdp("Emulation.setDeviceMetricsOverride",{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))");
  const layout=await evaluate("({viewport:innerWidth,width:document.documentElement.scrollWidth,client:document.documentElement.clientWidth})");
  if (layout.width > 391) {
    const wide = await evaluate("[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>391).map(e=>[e.tagName,e.id,e.className,e.getBoundingClientRect().right]).slice(0,14)");
    throw new Error("Mobile overflow: "+JSON.stringify({layout,wide}));
  }
  if(process.env.BAMBULOOP_QA_SCREENSHOT === "1"){
    const capture=await cdp("Page.captureScreenshot",{format:"png"});
    await fs.writeFile(path.join(scratchRoot,"mobile-preview.png"),Buffer.from(capture.data,"base64"));
  }
  assert.ok(served.some(([,u])=>u.endsWith(".wasm")) && served.some(([,u])=>u.endsWith("engine.zip")));
  assert.ok(served.every(([method,u])=>method==="GET" && !u.includes("/api/")));
  assert.ok(requests.every(u=>u.startsWith(origin+"/")||u.startsWith("blob:")||u.startsWith("data:")));
  assert.deepEqual(errors,[]);
  console.log("PASS · English first visit, localized titles and saved languages, GitHub/contribution links and dismissal, static offline UI, 2-plate 3MF/AMS/MD5, source bed and one/zero build-plate check, single retreat, 0 mm, English, dry-run, sound catalog, reset, 42 mm block, plain G-code");
  console.log("G-code commands SHA-256:",createHash("sha256").update(text.split(/\r?\n/).map(l=>l.split(";")[0].trim()).filter(Boolean).join("\n")).digest("hex"));
} catch(error) {
  if(evaluate) console.error(await evaluate("JSON.stringify({url:location.href,title:document.title,body:document.body?.textContent.slice(0,160),toast:document.querySelector('#toast')?.textContent,alert:document.querySelector('#alertModalBody')?.textContent,status:document.querySelector('#engineStatus')?.textContent})").catch(()=>null));
  console.error("Page errors:",errors,"static requests:",served.slice(-12)); throw error;
} finally {
  if(ws?.readyState===1) {ws.send(JSON.stringify({id:999999,method:"Browser.close"}));ws.close();}
  if(child) {
    if(await Promise.race([closed.then(()=>true),delay(3500).then(()=>false)])===false) {child.kill(); await closed;}
  }
  server.closeAllConnections();server.close();proxy.closeAllConnections();proxy.close();
  const final=await fs.realpath(scratch), parent=await fs.realpath(scratchRoot);
  if(path.dirname(final)===parent && path.basename(final).startsWith("pages-qa-")) {
    await fs.rm(final,{recursive:true,force:true,maxRetries:5,retryDelay:300});
  }
}
