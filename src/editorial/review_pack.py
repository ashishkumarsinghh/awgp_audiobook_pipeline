"""Portable, offline checking page accompanying an immutable audio submission."""
import html
import json
from pathlib import Path
import shutil

from src.core.artifacts import atomic_write, write_json


def create_review_pack(workspace, version, record):
    folder = workspace.home / "reviews" / version["id"]
    folder.mkdir(parents=True, exist_ok=True)
    build = workspace.home / "builds" / record["id"]
    shutil.copy2(build / "audiobook.mp3", folder / "audiobook.mp3")
    atomic_write(folder / "manuscript.txt", record["manuscript"])
    pdf = workspace.root / "00_scanned.pdf"
    if pdf.exists():
        shutil.copy2(pdf, folder / "source.pdf")
    previous_version = None
    review = workspace.home / "review.json"
    if review.exists():
        versions = json.loads(review.read_text(encoding="utf-8"))["versions"]
        index = next(n for n, v in enumerate(versions) if v["id"] == version["id"])
        previous_version = versions[index-1] if index else None
    old_offsets = {}
    if previous_version:
        previous = workspace.build_record(previous_version["build"])
        shutil.copy2(workspace.home / "builds" / previous["id"] / "audiobook.mp3", folder / "previous.mp3")
        old_offsets = {o["chunk_id"]: o for o in previous["offsets"]}
    payload = {"version": version["id"], "build": version["build"], "book": workspace.root.name,
               "passages": record["items"], "offsets": record["offsets"],
               "changed": version["changed"], "issues": workspace.issues(version["id"])}
    write_json(folder / "review.json", payload)
    cards = []
    for item, offset in zip(record["items"], record["offsets"]):
        pid = html.escape(item["id"], quote=True)
        changed = item["id"] in version["changed"]
        prior = old_offsets.get(item["id"])
        before = (f'<button data-old="{prior["start_seconds"]}">Play previous</button>' if prior else "")
        pdf_link = f'<a href="source.pdf#page={html.escape(str(item["pdf_page"]), quote=True)}" target="_blank">Open scan</a>' if pdf.exists() else ""
        cards.append(f'<article data-id="{pid}" data-changed="{str(changed).lower()}">'
                     f'<h2>Page {html.escape(str(item["page"]))} · {pid} {"· Changed" if changed else ""}</h2>'
                     f'<p>{html.escape(item["source_text"])}</p>'
                     f'<button data-start="{max(0, offset["start_seconds"]-2)}" data-end="{offset["end_seconds"]+2}">Play with context</button> '
                     f'{before} {pdf_link} <button data-report="{pid}">Report issue</button></article>')
    # JSON is escaped for script embedding, independently of HTML escaping.
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Audiobook review</title><style>
body{font:18px system-ui,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;background:#f6f7f9;color:#20252b}
header{position:sticky;top:0;background:#f6f7f9;padding:12px 0;border-bottom:1px solid #ccc}audio{width:100%}
article{background:white;border:1px solid #ddd;border-radius:8px;margin:16px 0;padding:18px}h2{font-size:16px;color:#526070}p{white-space:pre-wrap;line-height:1.8}
button,input,textarea,select{font:inherit;padding:8px;margin:5px}button{cursor:pointer}textarea{display:block;width:90%}.muted{color:#526070}#notes{white-space:pre-wrap}
</style><header><h1 id="title"></h1><audio id="player" controls></audio>
<label><input type="checkbox" id="changed"> Changed passages only</label>
<input id="search" placeholder="Search page, passage, or phrase"><input id="who" placeholder="Your name">
<button id="download">Download feedback</button><span id="saved" class="muted"></span></header>
<p>Listen against the scan. Notes stay in this browser when storage is available; download feedback before closing or moving this folder.</p>
<section id="existing"></section><div id="cards">CARDS</div><h2>Your feedback</h2><div id="notes"></div>
<script>const data=DATA;
const player=document.getElementById('player'), pending=[], key='audiobook-review-'+data.build;
let stopAt=null;
try{pending.push(...JSON.parse(localStorage.getItem(key)||'[]'));document.getElementById('who').value=localStorage.getItem(key+'-who')||''}catch(e){}
document.getElementById('title').textContent=data.book+' · '+data.version;
player.src='audiobook.mp3';
function save(){try{localStorage.setItem(key,JSON.stringify(pending));localStorage.setItem(key+'-who',document.getElementById('who').value)}catch(e){}document.getElementById('notes').textContent=pending.map(n=>n.passage+': '+(n.status||n.body)).join('\\n');document.getElementById('saved').textContent=pending.length+' notes';}
function seek(file,start,end){player.pause();stopAt=end;const go=()=>{player.currentTime=start;player.play().catch(()=>{})};if(!player.src.endsWith('/'+file)){player.src=file;player.addEventListener('loadedmetadata',go,{once:true})}else go();}
player.addEventListener('timeupdate',()=>{if(stopAt!==null&&player.currentTime>=stopAt)player.pause()});
document.getElementById('cards').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
if(b.dataset.start)seek('audiobook.mp3',Number(b.dataset.start),Number(b.dataset.end));
else if(b.dataset.old)seek('previous.mp3',Number(b.dataset.old),null);
else if(b.dataset.report){const body=prompt('Describe the problem and intended correction:');if(body&&body.trim()){pending.push({passage:b.dataset.report,body:body.trim()});save()}}});
function filter(){const q=document.getElementById('search').value.toLowerCase(),changed=document.getElementById('changed').checked;document.querySelectorAll('article').forEach(a=>a.hidden=(changed&&a.dataset.changed!=='true')||!a.textContent.toLowerCase().includes(q));}
document.getElementById('search').oninput=filter;document.getElementById('changed').onchange=filter;
data.issues.forEach(i=>{const box=document.createElement('article'),title=document.createElement('p');title.textContent=i.id+' ['+i.status+'] '+i.body;box.append(title);
i.current_times.forEach(t=>{const b=document.createElement('button');b.textContent='Play corrected passage';b.onclick=()=>seek('audiobook.mp3',Math.max(0,t.start_seconds-2),t.end_seconds+2);box.append(b)});
(i.status==='ready_to_recheck'||i.status==='reopened'?['verified','reopened']:['reopened']).forEach(status=>{const b=document.createElement('button');b.textContent=status==='verified'?'Verified':'Reopen';b.onclick=()=>{const old=pending.findIndex(n=>n.issue===i.id);if(old>=0)pending.splice(old,1);pending.push({issue:i.id,passage:i.passage,status});save()};box.append(b)});document.getElementById('existing').append(box)});
document.getElementById('download').onclick=()=>{const reporter=document.getElementById('who').value.trim();if(!reporter){alert('Enter your name first.');return}save();const blob=new Blob([JSON.stringify({version:data.version,build:data.build,reporter,notes:pending},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=data.book+'-'+data.version+'-feedback.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};save();
</script></html>""".replace("DATA", data, 1).replace("CARDS", "\n".join(cards), 1)
    atomic_write(folder / "index.html", page)
    return folder
