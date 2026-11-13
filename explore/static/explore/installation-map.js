/* #219: the 3D installation map — a schematic model of the FD-VD cryostat (to scale from the 2024 installation
   document), every drawn component a named position, each kind of position linked to an HWDB component type.
   Ported from the mock-up (.idea/spike/install-mock/map.html). The scene is built in code below; it becomes a
   data file when a second drawing needs the viewer. Page data: #im-data (explore_installation_map_view). */
(function(){
"use strict";
var D=JSON.parse(document.getElementById("im-data").textContent);
var $=function(id){return document.getElementById("im-"+id)};
var STEPS=["DAQ in the barracks","BDE, PD and HV roof equipment","TDE chimneys and readout crates","Set up and clean","HV extender and feedthrough","Wall and roof services","CRP support structures","Top CRPs","Cathodes","Field cage walls","Bottom CRPs, rows 1 to 19","West end wall, top rows","Bottom CRPs, row 20","West end wall, bottom row","Close the TCO"];
var DESC=["Commercial DAQ equipment goes into 16 racks in the DAQ barracks.", "Rack modules go onto the detector mezzanine. A gantry cart sets 40 vacuum crosses on the roof penetrations; each is leak tested.", "105 chimneys are lowered through the roof at the corners of the CRPs. Crates and blades follow before CRP installation starts.", "Greyroom in operation, TCO hoisting beam in, scissor lifts in, cryostat cleaned.", "The extender hangs from a roof penetration on the east wall. The feedthrough is lowered through the roof and leak checked.", "44 strings of X-ARAPUCA modules, BDE cable trays at the 40 feedthroughs, cable trays for the top CRPs below the chimneys.", "Each stainless support structure is bolted together on the floor, winched up, shimmed and surveyed.", "Two half-size CRUs are joined into a CRP, raised on a lift table, cabled, then linked to its support structure.", "Cathode modules with their X-ARAPUCAs are raised in pairs, get their PD fibres and meshes, then hang at the drift gap.", "Each support beam is raised in stages while 8 modules are hung beneath it. East end wall first, then north and south.", "Row by row: lift the false floor, lay out cables, set the CRP on the truss, connect, test, lower onto the membrane floor.", "The TCO beam comes out. The top three rows of west end wall modules are lifted onto the installation cart and hung.", "The north and south CRPs go in whole. The last two are placed as half-size CRUs.", "The last four modules are carried by hand into the 700 mm gap and bolted on.", "Clean, install the bottom purity monitor, remove ramp and ladders, close the manholes."];
var N=STEPS.length, END=0.9999, STEP_SEC=4;
/* the plan's own words for a step, when the plan has that step number */
function stepName(i){ var s=D.steps[i+1]; return (s&&s.name)||STEPS[i]; }
function stepDesc(i){ var s=D.steps[i+1]; return s?s.note:DESC[i]; }
/* kinds of displayed position; a kind's type is its link (D.links) */
var KINDS=[
 {id:"daq",name:"DAQ rack"},{id:"cross",name:"BDE/PD vacuum cross"},{id:"chim",name:"TDE chimney"},{id:"hv",name:"HV extender"},
 {id:"pds",name:"Membrane PD string"},{id:"sst",name:"CRP support structure"},{id:"tcrp",name:"Top CRP"},{id:"cath",name:"Cathode module"},
 {id:"fc",name:"Field cage module"},{id:"bcrp",name:"Bottom CRP"},{id:"bcru",name:"Bottom CRU (half CRP)"}
];
var KBY={}; KINDS.forEach(function(k){ KBY[k.id]=k; k.pos=[]; k.type=D.links[k.id]||""; });
var ITEMS={}, statusNote="reading HWDB…";   /* type id → {position name: part id}, the page's status read */
function typeName(id){ return D.names[id]||""; }

var POS=[];
function pos(kind,name,step,c){ var p={i:POS.length,name:name,kind:kind,step:step,c:c,n:KBY[kind].pos.length}; POS.push(p); KBY[kind].pos.push(p); return p.i; }
function pad(n){ return (n<10?"0":"")+n; }
function pidOf(p){ var t=KBY[p.kind].type; return (t&&ITEMS[t]&&ITEMS[t][p.name])||""; }
function stOf(p){ return pidOf(p)?"inst":"pend"; }
var STL={inst:"Installed",pend:"Pending"};

var mode="status", sel=-1, T=0, cur=-1, playing=false, stopAt=END, dirty=true, openKind={}, pickKind="";
var reduce=window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- step bar ---------- */
var chips=[];
STEPS.forEach(function(s,i){ var b=document.createElement("button"); b.type="button"; b.className="im-chip"; b.textContent=String(i+1); b.title=stepName(i);
  b.setAttribute("role","listitem"); b.setAttribute("aria-label","Step "+(i+1)+": "+stepName(i));
  b.addEventListener("click",function(){ setMode("plan"); goStep(i); }); $("chips").appendChild(b); chips.push(b); });
function goStep(i){ if(reduce){ T=i+END; playing=false; } else { T=i; stopAt=i+END; playing=true; } dirty=true; syncPlay(); }
/* transport: Play runs on through the steps from where the view is, Previous / Next replay one step */
function syncPlay(){ $("play").textContent=playing?"Pause":(T>=N-1+END-1e-6?"Replay":"Play"); }
$("play").addEventListener("click",function(){ setMode("plan");
  if(playing) playing=false; else { if(T>=N-1+END-1e-6) T=0; stopAt=N-1+END; playing=true; }
  dirty=true; syncPlay(); });
$("prev").addEventListener("click",function(){ setMode("plan"); goStep(Math.max(0,cur-1)); });
$("next").addEventListener("click",function(){ setMode("plan"); goStep(Math.min(N-1,cur+1)); });
function showCap(){
  if(mode==="status"){
    var c={inst:0,pend:0}; POS.forEach(function(p){c[stOf(p)]++});
    $("cap").innerHTML='<div class="im-legend"><span><i class="im-sw" style="background:var(--good)"></i>Installed '+c.inst+'</span><span><i class="im-sw" style="background:var(--surface-2)"></i>Pending '+c.pend+'</span><span><i class="im-sw" style="background:var(--im-pick)"></i>Selected</span>'+(statusNote?'<span class="im-none">'+esc(statusNote)+"</span>":"")+"</div>";
    chips.forEach(function(ch){ ch.classList.remove("done"); ch.removeAttribute("aria-current"); });
  } else {
    $("cap").innerHTML="<b>Step "+(cur+1)+" · "+esc(stepName(cur))+'</b> · <a href="'+D.plan_url+"#step-"+(cur+1)+'">steps table</a><div class="im-desc">'+esc(stepDesc(cur))+"</div>";
    chips.forEach(function(ch,k){ ch.classList.toggle("done",k<cur); if(k===cur)ch.setAttribute("aria-current","step"); else ch.removeAttribute("aria-current"); });
  }
}
function setMode(m){ if(mode===m)return; mode=m; $("plan").setAttribute("aria-pressed",String(m==="plan")); $("status").setAttribute("aria-pressed",String(m==="status"));
  if(m==="status"){ playing=false; syncPlay(); goal=view(SVIEW); } else if(cur>=0) goal=view(VIEWS[cur]);
  dirty=true; showCap(); }
$("plan").addEventListener("click",function(){ setMode("plan"); goStep(Math.max(0,cur)); });
$("status").addEventListener("click",function(){ setMode("status"); });
function esc(s){ return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]}); }

if(!window.THREE){ $("nogl").hidden=false; $("nogl").textContent="The 3D library failed to load."; return; }
var canvas=$("gl"), stage=$("stage"), renderer;
try{ renderer=new THREE.WebGLRenderer({canvas:canvas,antialias:true}); }catch(e){ $("nogl").hidden=false; return; }
renderer.setPixelRatio(Math.min(2,window.devicePixelRatio||1));
renderer.setClearColor(0xfbf8f1,1);

/* ---------- scene (schematic, to scale from the 2024 installation plan) ---------- */
var L=62,W=15.1,H=14,hx=L/2,hz=W/2,DEG=Math.PI/180;
var scene=new THREE.Scene(), camera=new THREE.PerspectiveCamera(35,1,0.5,600);
scene.add(new THREE.HemisphereLight(0xffffff,0x9a9488,0.95));
var sun=new THREE.DirectionalLight(0xffffff,0.55); sun.position.set(40,80,50); scene.add(sun);
var BOX=new THREE.BoxGeometry(1,1,1), CYL=new THREE.CylinderGeometry(1,1,1,18);
function mat(c,o){ return new THREE.MeshStandardMaterial(Object.assign({color:c,roughness:.7,metalness:.1},o||{})); }
function box(sx,sy,sz,x,y,z,m){ var b=new THREE.Mesh(BOX,m); b.scale.set(sx,sy,sz); b.position.set(x,y,z); scene.add(b); return b; }
var shellC=0xb5ad9c, mN=mat(shellC), mS=mat(shellC), mE=mat(shellC), mWw=mat(shellC), mRoof=mat(0xbdb6a6);
box(L+1.6,0.3,W+1.6,0,-0.15,0,mat(0xc8c1b0));
box(L,H,0.8,0,H/2,-(hz+0.4),mN); box(L,H,0.8,0,H/2,(hz+0.4),mS); box(0.8,H,W+1.6,hx+0.4,H/2,0,mE);
var TW=1.8,TH=8;
box(0.8,H,(hz+0.8-TW),-(hx+0.4),H/2,-(TW+(hz+0.8-TW)/2),mWw);
box(0.8,H,(hz+0.8-TW),-(hx+0.4),H/2,(TW+(hz+0.8-TW)/2),mWw);
box(0.8,H-TH,2*TW,-(hx+0.4),TH+(H-TH)/2,0,mWw);
box(L+1.6,1,W+1.6,0,H+0.5,0,mRoof);
var edgeMat=new THREE.LineBasicMaterial({color:0x1c1812,transparent:true,opacity:.4});
var outline=new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(L+1.6,H+1,W+1.6)),edgeMat); outline.position.set(0,(H+1)/2,0); scene.add(outline);
box(44.5,0.2,3.4,0.25,H+0.9,-(hz+0.8+1.7),mat(0xa39c8c));
var barracks=new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(9.4,3.4,6.4)),edgeMat); barracks.position.set(39.2,1.7,0); scene.add(barracks);
var greyroom=new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(15.2,9,14)),edgeMat); greyroom.position.set(-39.4,4.5,0); scene.add(greyroom);
var beam=box(10,0.35,0.35,-31,7.5,0,mat(0xd8a21c));   /* TCO hoisting beam, steps 4 to 11 */
var jib=new THREE.Group();   /* jib crane at the TCO, steps 13 and 14 */
(function(){ var m=mat(0xd8a21c),a=new THREE.Mesh(BOX,m); a.scale.set(5.5,.25,.25); a.position.set(-30.4,7.2,1.2); jib.add(a);
  var q=new THREE.Mesh(BOX,m); q.scale.set(.3,7.2,.3); q.position.set(-33,3.6,1.2); jib.add(q); scene.add(jib); })();
var tco=box(0.8,TH,2*TW,-(hx+0.4),TH/2,0,mat(0x8f8878));
var argon=new THREE.Mesh(BOX,new THREE.MeshBasicMaterial({color:0x6fb4ea,transparent:true,opacity:.26,depthWrite:false})); scene.add(argon);

var groups=[];
function group(geo,base,m){ var g={geo:geo,base:new THREE.Color(base),mat:m||mat(0xffffff),specs:[]}; groups.push(g); return g; }
function add(g,o){ var s={p:[0,0,0],f:[0,0,0],t0:-1,t1:-0.5,out:1e9,step:-1,ry:0,rz:0,s:[1,1,1],pos:-1}; for(var k in o)s[k]=o[k]; g.specs.push(s); return s; }
function seq(k,a,b,i,n,mul){ var sp=(b-a)/n,t0=k+a+i*sp; return [t0,Math.min(k+0.97,t0+sp*(mul||1))]; }
var stripes=(function(){ var c=document.createElement("canvas"); c.width=4; c.height=64; var x=c.getContext("2d");
  for(var i=0;i<16;i++){ x.fillStyle=i%2?"#9a9488":"#f0ece2"; x.fillRect(0,i*4,4,4); }
  var t=new THREE.CanvasTexture(c); t.magFilter=THREE.NearestFilter; return t; })();
var gRack=group(BOX,0x2f5fa8), gSteel=group(CYL,0xb9c2c7), gChim=group(CYL,0xa8b2b8), gCrate=group(BOX,0x2c333a),
    gLift=group(BOX,0xe0b422), gHV=group(CYL,0xd5d9dc), gRod=group(CYL,0x7d878d), gPD=group(BOX,0x2f9ac4), gCable=group(BOX,0x8a6fb0), gTray=group(BOX,0x8a9197),
    gSST=group(BOX,0x9aa4aa), gCham=group(CYL,0x77838a), gCRP=group(BOX,0x4f9d72), gCath=group(BOX,0x3d434b), gFloor=group(BOX,0xcdb48e);
function fcMat(){ return mat(0xffffff,{map:stripes,metalness:.3,roughness:.5}); }
var gFC={N:group(BOX,0xffffff,fcMat()),S:group(BOX,0xffffff,fcMat()),E:group(BOX,0xffffff,fcMat()),W:group(BOX,0xffffff,fcMat())};
var i,j,k,m,n,tt,p;
function rowX(r){ return 28.5-3*r; } function colZ(c){ return -5.0625+3.375*c; }
for(i=0;i<16;i++){ tt=seq(0,.1,.85,i,16,1.5); var dp=[35.7+(i%8)*1.0,1.05,i<8?-1.3:1.3];
  add(gRack,{p:dp,s:[.8,2.1,.9],f:[0,3,0],t0:tt[0],t1:tt[1],step:0,pos:pos("daq","DAQ-"+pad(i+1),0,dp)}); }
for(i=0;i<30;i++){ k=i<18?1:2; tt=i<18?seq(1,.02,.14,i,18,2):seq(2,.02,.08,i-18,12,2);
  add(gRack,{p:[-20+i*1.4,H+2.05,-(hz+0.8+1.9)],s:[.8,2.1,.9],f:[0,2.5,0],t0:tt[0],t1:tt[1],step:k}); }
for(i=0;i<20;i++)for(j=0;j<2;j++){ var sg=j?1:-1; tt=seq(1,.16,.92,i*2+j,40,1.6); var cp=[rowX(i),H+1.65,sg*7.0];
  p=pos("cross","XC-"+(j?"S":"N")+pad(i+1),1,cp);
  add(gSteel,{p:cp,s:[.22,1.3,.22],f:[0,5,0],t0:tt[0],t1:tt[1],step:1,pos:p});
  add(gSteel,{p:[rowX(i),H+1.75,sg*7.0],s:[.18,1.15,.18],rz:90*DEG,f:[0,5,0],t0:tt[0],t1:tt[1],step:1,pos:p}); }
for(k=0;k<21;k++)for(m=0;m<5;m++){ n=k*5+m; var cx=30-3*k,cz=-6.75+3.375*m,r=(m===0||m===4)?.2:.3;
  tt=seq(2,.09,.7,n,105,3);
  add(gChim,{p:[cx,H+0.6,cz],s:[r,2.6,r],f:[0,6,0],t0:tt[0],t1:tt[1],step:2,pos:pos("chim","CH-"+pad(k+1)+"-"+(m+1),2,[cx,H+0.6,cz])});
  tt=seq(2,.72,.94,n,105,3);
  add(gCrate,{p:[cx+0.62,H+1.18,cz],s:[.5,.35,.4],f:[0,1.5,0],t0:tt[0],t1:tt[1],step:2});
  var tx=5.05+(30-cx)/60*0.78;
  add(gTray,{p:[cx,13.95,cz],s:[2.4,.05,.28],f:[0,-1.5,0],t0:tx+.04,t1:tx+.12,step:5});
}
[-1,1].forEach(function(sg){   /* step 4: scissor lifts, working until the top CRPs hang */
  add(gLift,{p:[0,0.95,0],s:[2.2,.9,1.2],t0:3.1,t1:3.11,out:6.02,step:3,lift:sg});
  add(gLift,{p:[0,5.4,0],s:[.25,8,.25],t0:3.1,t1:3.11,out:6.02,step:3,lift:sg});
  add(gLift,{p:[0,9.5,0],s:[2.2,.15,1.2],t0:3.1,t1:3.11,out:6.02,step:3,lift:sg}); });
p=pos("hv","HV extender",4,[30.65,8,0]);
add(gHV,{p:[30.65,10.4,0],s:[.22,7,.22],f:[0,-7,0],t0:4.12,t1:4.55,step:4,pos:p});
add(gHV,{p:[30.65,6.85,0],s:[.42,.3,.42],f:[0,-7,0],t0:4.12,t1:4.55,step:4,pos:p});
add(gHV,{p:[30.65,H+1.3,0],s:[.16,3.4,.16],f:[0,5,0],t0:4.6,t1:4.9,step:4,pos:p});
var pdY=[12.6,11.8,11.0,10.2,3.8,3.0,2.2,1.4];
function pdString(x,z,ry,t0,name){ var q=pos("pds",name,5,[x,7,z]);
  add(gRod,{p:[x,7,z],s:[.035,13.2,.035],f:[0,-1,0],t0:t0,t1:t0+.08,step:5,pos:q});
  pdY.forEach(function(y){ add(gPD,{p:[x-(ry?(x>0?.08:-.08):0),y,z-(ry?0:(z>0?.08:-.08))],s:[.62,.62,.07],ry:ry,f:[0,-1,0],t0:t0+.02,t1:t0+.1,step:5,pos:q}); }); }
pdString(30.85,-3.4,90*DEG,5.02,"PDS-E1"); pdString(30.85,3.4,90*DEG,5.03,"PDS-E2");
for(i=0;i<20;i++)[-1,1].forEach(function(sg){ var x=rowX(i),tx=5.05+(30-x)/60*0.78;
  pdString(x+0.9,sg*7.38,0,tx,"PDS-"+(sg>0?"S":"N")+pad(i+1));
  add(gCable,{p:[x-0.9,6.85,sg*7.42],s:[.5,13.3,.05],grow:1,t0:tx+.02,t1:tx+.12,step:5});
  add(gCable,{p:[x-0.9,0.1,sg*3.9],s:[.4,.06,7.0],t0:tx+.1,t1:tx+.12,step:5}); });
pdString(-30.85,-3.4,90*DEG,5.87,"PDS-W1"); pdString(-30.85,3.4,90*DEG,5.88,"PDS-W2");
var sx=[[28.5,3],[22.5,9],[13.5,9],[4.5,9],[-4.5,9],[-13.5,9],[-22.5,9],[-28.5,3]];
sx.forEach(function(e,a){ [-1,1].forEach(function(sg,b){ n=a*2+b; var z=sg*3.375;
  [-1,1].forEach(function(u){[-1,1].forEach(function(v){ tt=seq(6,.02,.11,n,16,2);
    add(gCham,{p:[e[0]+u*e[1]*.33,H+1.35,z+v*2.2],s:[.28,.7,.28],f:[0,3,0],t0:tt[0],t1:tt[1],step:6}); });});
  tt=seq(6,.13,.93,n,16,1.7);
  add(gSST,{p:[e[0],13.62,z],s:[e[1]-.2,.22,6.55],f:[0,-12.4,0],t0:tt[0],t1:tt[1],step:6,pos:pos("sst","SST-"+pad(n+1),6,[e[0],13.62,z])});
});});
function rc(i,j){ return "R"+pad(i+1)+"-C"+(j+1); }
for(i=0;i<20;i++)for(j=0;j<4;j++){ n=i*4+j;
  tt=seq(7,.03,.93,n,80,4);
  add(gCRP,{p:[rowX(i),13.36,colZ(j)],s:[2.92,.12,3.3],f:[0,-12,0],t0:tt[0],t1:tt[1],step:7,pos:pos("tcrp","TCRP "+rc(i,j),7,[rowX(i),13.36,colZ(j)])});
  tt=seq(8,.03,.93,Math.floor(n/2),40,3);
  add(gCath,{p:[rowX(i),6.75,colZ(j)],s:[2.92,.1,3.3],f:[0,-5.6,0],t0:tt[0],t1:tt[1],step:8,pos:pos("cath","CATH "+rc(i,j),8,[rowX(i),6.75,colZ(j)])});
}
var fcTop=11.65,fcH=3.2;
function fcMod(g,x,z,ry,w,row,a,b,step,name){ var y=fcTop-fcH*row; add(g,{p:[x,y,z],s:[w,3.1,.07],ry:ry,t0:a,t1:b,step:step,hang:row,pos:pos("fc",name+"-"+(row+1),step,[x,y,z])}); }
for(var e=0;e<2;e++)for(var c=0;c<2;c++)for(r=0;r<4;r++){ var a0=9.03+e*.055; fcMod(gFC.E,30.25,colZ(e*2+c),90*DEG,3.3,r,a0,a0+.055,9,"FC-E"+(e*2+c+1)); }
for(i=0;i<10;i++)for(c=0;c<2;c++)for(r=0;r<4;r++){ var a1=9.15+i*.078;
  fcMod(gFC.N,rowX(2*i+c),-6.95,0,2.92,r,a1,a1+.075,9,"FC-N"+pad(2*i+c+1)); fcMod(gFC.S,rowX(2*i+c),6.95,0,2.92,r,a1,a1+.075,9,"FC-S"+pad(2*i+c+1)); }
for(c=0;c<4;c++){ var a2=11.2+(c<2?0:1)*.36;
  for(r=0;r<3;r++) fcMod(gFC.W,-30.25,colZ(c),90*DEG,3.3,r,a2,a2+.34,11,"FC-W"+(c+1));
  tt=seq(13,.1,.9,c,4,1); var wp=[-30.25,fcTop-fcH*3,colZ(c)];
  add(gFC.W,{p:wp,s:[3.3,3.1,.07],ry:90*DEG,f:[1.6,0,0],t0:tt[0],t1:tt[1],step:13,pos:pos("fc","FC-W"+(c+1)+"-4",13,wp)});
}
var rowDur=.92/19; function rowT(r){ return 10.03+r*rowDur; }
for(i=0;i<20;i++) add(gFloor,{p:[rowX(i),.46,0],s:[2.98,.08,13.3],out:i<19?rowT(i):12.05,floor:1});
add(gFloor,{p:[30.5,.46,0],s:[1,.08,13.3],out:10.03,floor:1});
add(gFloor,{p:[-30.5,.46,0],s:[1,.08,13.3],out:14.05,floor:1});
for(i=0;i<19;i++)for(j=0;j<4;j++){ var b0=rowT(i)+rowDur*(.15+.2*j), bp=[rowX(i),.3,colZ(j)];
  add(gCRP,{p:bp,s:[2.92,.12,3.3],f:[-4,1.6,0],t0:b0,t1:b0+rowDur*.25,step:10,pos:pos("bcrp","BCRP "+rc(i,j),10,bp)}); }
[[0,12.2],[3,12.38]].forEach(function(q){ var bp=[rowX(19),.3,colZ(q[0])];
  add(gCRP,{p:bp,s:[2.92,.12,3.3],f:[-5,3,-colZ(q[0])*.8],t0:q[1],t1:q[1]+.22,step:12,pos:pos("bcrp","BCRP "+rc(19,q[0]),12,bp)}); });
n=0; [1,2].forEach(function(jj){ [-.73,.73].forEach(function(dx,h){ var c0=12.62+n*.08; n++; var bp=[rowX(19)+dx,.3,colZ(jj)];
  add(gCRP,{p:bp,s:[1.44,.12,3.3],f:[-5,3,-colZ(jj)*.8],t0:c0,t1:c0+.1,step:12,pos:pos("bcru","BCRU "+rc(19,jj)+(h?"b":"a"),12,bp)}); }); });

var meshes=[];
groups.forEach(function(g){ g.mesh=new THREE.InstancedMesh(g.geo,g.mat,g.specs.length); g.mesh.frustumCulled=false; g.mesh.userData.g=g;
  for(var q=0;q<g.specs.length;q++) g.mesh.setColorAt(q,g.base); scene.add(g.mesh); meshes.push(g.mesh); });

/* ---------- camera ---------- */
var VIEWS=[[8,7,0,92,60,62],[0,14,0,80,70,46],[0,14,0,80,70,46],[-27,5,0,50,112,66],[25,8,0,42,112,72],[0,7,0,78,75,66],[0,9,0,76,75,78],[0,9,0,76,75,80],[0,7,0,74,75,78],[0,7,0,78,62,64],[0,3,0,72,75,80],[-22,7,0,56,76,70],[-22,5,0,54,76,72],[-22,6,0,56,76,70],[-20,7,0,62,116,66]];
var SVIEW=[4,7,0,84,68,64];
var cam={t:new THREE.Vector3(4,7,0),r:84,th:68*DEG,ph:64*DEG}, goal=null;
function fit(){ return Math.max(1,Math.min(2.6,1.45/camera.aspect)); }
function view(v){ return {t:new THREE.Vector3(v[0],v[1],v[2]),r:v[3]*fit(),th:v[4]*DEG,ph:v[5]*DEG}; }
function applyGoal(a){ cam.t.lerp(goal.t,a); cam.r+=(goal.r-cam.r)*a; cam.th+=(goal.th-cam.th)*a; cam.ph+=(goal.ph-cam.ph)*a; }
function placeCamera(){ var sp=Math.sin(cam.ph);
  camera.position.set(cam.t.x+cam.r*sp*Math.cos(cam.th),cam.t.y+cam.r*Math.cos(cam.ph),cam.t.z+cam.r*sp*Math.sin(cam.th)); camera.lookAt(cam.t); }
var ptrs={}, lastPinch=0, ray=new THREE.Raycaster(), ndc=new THREE.Vector2();
canvas.addEventListener("contextmenu",function(e){e.preventDefault()});
canvas.addEventListener("pointerdown",function(e){ canvas.setPointerCapture(e.pointerId); ptrs[e.pointerId]={x:e.clientX,y:e.clientY,b:e.button,sh:e.shiftKey,moved:0}; lastPinch=0; });
canvas.addEventListener("pointermove",function(e){
  var q=ptrs[e.pointerId]; if(!q)return; var dx=e.clientX-q.x,dy=e.clientY-q.y; q.x=e.clientX; q.y=e.clientY; q.moved+=Math.abs(dx)+Math.abs(dy);
  if(q.moved<5)return; goal=null;
  var ids=Object.keys(ptrs);
  if(ids.length>=2){ var a=ptrs[ids[0]],b=ptrs[ids[1]],d=Math.hypot(a.x-b.x,a.y-b.y); if(lastPinch)cam.r=Math.max(6,Math.min(260,cam.r*lastPinch/d)); lastPinch=d; return; }
  if(q.b===2||q.sh){ var s=cam.r*.0011,right=new THREE.Vector3(),up=new THREE.Vector3(); camera.matrixWorld.extractBasis(right,up,new THREE.Vector3()); cam.t.addScaledVector(right,-dx*s).addScaledVector(up,dy*s); }
  else { cam.th+=dx*.006; cam.ph=Math.max(.08,Math.min(Math.PI-.08,cam.ph-dy*.006)); }
});
function endPtr(e){ var q=ptrs[e.pointerId]; delete ptrs[e.pointerId]; lastPinch=0;
  if(q&&q.moved<5&&e.type==="pointerup"&&q.b===0){
    var rct=canvas.getBoundingClientRect(); ndc.set((e.clientX-rct.left)/rct.width*2-1,-((e.clientY-rct.top)/rct.height)*2+1);
    ray.setFromCamera(ndc,camera); var hits=ray.intersectObjects(meshes,false), found=-1;
    for(var h=0;h<hits.length;h++){ var s=hits[h].object.userData.g.specs[hits[h].instanceId]; if(s&&s.vis&&s.pos>=0){ found=s.pos; break; } }
    select(found,false);
  } }
canvas.addEventListener("pointerup",endPtr); canvas.addEventListener("pointercancel",endPtr);
canvas.addEventListener("wheel",function(e){ e.preventDefault(); goal=null; cam.r=Math.max(6,Math.min(260,cam.r*Math.exp(e.deltaY*.001))); },{passive:false});

/* ---------- draw ---------- */
function clamp(v,a,b){ return v<a?a:(v>b?b:v); } function ease(q){ return q*q*(3-2*q); } function lerp(a,b,q){ return a+(b-a)*clamp(q,0,1); }
function liftX(t){ return t<3.6?lerp(-35,-22,(t-3.1)/.5):t<4.05?-22:t<4.35?lerp(-22,26,(t-4.05)/.3):t<5.03?26:lerp(26,-26,(t-5.03)/.87); }
function liftZ(t){ return t<3.35?.9:lerp(.9,5.4,(t-3.35)/.25); }
var cWork=new THREE.Color(0xc9560f), cSel=new THREE.Color(0x2f55d4), cSt={inst:new THREE.Color(0x4a8a5a),pend:new THREE.Color(0xe2dccb)};
var M=new THREE.Matrix4(),P=new THREE.Vector3(),Q=new THREE.Quaternion(),S=new THREE.Vector3(),E=new THREE.Euler(),ZERO=new THREE.Matrix4().makeScale(0,0,0);
function apply(){
  T=clamp(T,0,N-1+END);
  var c=Math.floor(T); if(c!==cur){ cur=c; if(mode==="plan"){ goal=view(VIEWS[c]); } showCap(); }
  var status=mode==="status";
  for(var gi=0;gi<groups.length;gi++){ var g=groups[gi],me=g.mesh;
    for(var q=0;q<g.specs.length;q++){ var s=g.specs[q],x=s.p[0],y=s.p[1],z=s.p[2],sy=s.s[1],col=g.base;
      if(status){
        s.vis=s.pos>=0||(!s.floor&&!s.lift&&s.step<=6);
        if(s.pos>=0) col=cSt[stOf(POS[s.pos])];
      } else {
        s.vis=T>s.t0&&T<s.out;
        if(s.vis){ var pr=clamp((T-s.t0)/(s.t1-s.t0),0,1),e=ease(pr);
          if(s.hang!==undefined){ var qq=pr*3; if(qq<s.hang-1e-6)s.vis=false; else y-=fcH*clamp(3-qq,0,3); }
          else if(s.grow){ sy=Math.max(.001,s.s[1]*e); y=(s.p[1]-s.s[1]/2)+sy/2; }
          else if(s.lift){ x=liftX(T); z=s.lift*liftZ(T); }
          else { x+=s.f[0]*(1-e); y+=s.f[1]*(1-e); z+=s.f[2]*(1-e); }
          if(s.step===cur) col=cWork; }
      }
      if(!s.vis){ me.setMatrixAt(q,ZERO); continue; }
      if(s.pos>=0&&s.pos===sel) col=cSel;
      P.set(x,y,z); E.set(0,s.ry,s.rz); Q.setFromEuler(E); S.set(s.s[0],sy,s.s[2]); M.compose(P,Q,S);
      me.setMatrixAt(q,M); me.setColorAt(q,col);
    }
    me.instanceMatrix.needsUpdate=true; if(me.instanceColor)me.instanceColor.needsUpdate=true;
  }
  greyroom.visible=status||T>3.04; beam.visible=!status&&T>3.25&&T<11.06; jib.visible=!status&&T>12.04&&T<14.04;
  tco.visible=!status&&T>14.2; tco.position.x=-(hx+0.4)-4*(1-ease(clamp((T-14.2)/.36,0,1)));
  var lv=status?0:13.7*clamp((T-14.62)/.36,0,1); argon.visible=lv>0; argon.scale.set(L-.05,Math.max(.01,lv),W-.05); argon.position.set(0,lv/2,0);
}
function fade(mt,on,op){ if(mt.transparent!==on){ mt.transparent=on; mt.depthWrite=!on; mt.needsUpdate=true; } mt.opacity=on?op:1; }
function cutaway(){ var c=camera.position;
  fade(mN,c.z<-hz,.1); fade(mS,c.z>hz,.1); fade(mE,c.x>hx,.1); fade(mWw,c.x<-hx,.1);
  fade(gFC.N.mat,c.z<-6.9,.2); fade(gFC.S.mat,c.z>6.9,.2); fade(gFC.E.mat,c.x>30.2,.2); fade(gFC.W.mat,c.x<-30.2,.2);
  var see=roofUser===null?(mode==="status"||cur>=3):roofUser;
  if(see!==roofSee){ roofSee=see; $("roof").setAttribute("aria-pressed",String(see)); }
  fade(mRoof,see,.13); }
var roofUser=null, roofSee=null;
$("roof").addEventListener("click",function(){ roofUser=!roofSee; });
var cw=0,ch=0;
function resize(){ var w=stage.clientWidth,h=stage.clientHeight; if(!w||!h||(w===cw&&h===ch))return; var first=!cw; cw=w; ch=h;
  renderer.setSize(w,h,false); camera.aspect=w/h; camera.updateProjectionMatrix(); if(first){ goal=view(SVIEW); applyGoal(1); goal=null; } }
var last=null;
function frame(now){ var dt=last===null?0:Math.min(.1,(now-last)/1000); last=now; resize();
  if(playing){ T+=dt/STEP_SEC; if(T>=stopAt){ T=stopAt; playing=false; syncPlay(); } dirty=true; }
  if(dirty){ apply(); dirty=false; }
  if(goal){ if(reduce){ applyGoal(1); goal=null; } else { applyGoal(1-Math.exp(-dt*2.6)); if(Math.abs(goal.r-cam.r)<.02&&Math.abs(goal.th-cam.th)<.001&&goal.t.distanceTo(cam.t)<.02)goal=null; } }
  placeCamera(); camera.updateMatrixWorld(); cutaway(); renderer.render(scene,camera); requestAnimationFrame(frame); }

/* ---------- side panel ---------- */
function select(i,fly){ sel=i; dirty=true;
  if(i>=0){ var p=POS[i]; openKind[p.kind]=true; if(fly) goal={t:new THREE.Vector3(p.c[0],p.c[1],p.c[2]),r:30*fit(),th:cam.th,ph:cam.ph}; }
  renderSel(); renderKinds();
  if(i>=0&&!fly){ var el=document.querySelector('.im-plist button[aria-current="true"]'); if(el&&el.scrollIntoView) el.scrollIntoView({block:"nearest"}); } }
function typeLink(t){ return '<a class="im-tid" href="'+D.type_url+t+'">'+t+"</a> "+esc(typeName(t)); }
function renderSel(){
  if(sel<0){ $("sel").innerHTML=""; return; }
  var p=POS[sel],k=KBY[p.kind],pid=pidOf(p);
  $("sel").innerHTML='<div class="im-card"><div class="im-nm">'+esc(p.name)+'</div><dl class="im-kv">'+
    "<dt>Kind</dt><dd>"+esc(k.name)+"</dd>"+
    "<dt>Type</dt><dd>"+(k.type?typeLink(k.type):'<span class="im-none">not linked</span>')+"</dd>"+
    '<dt>Step</dt><dd><a href="'+D.plan_url+"#step-"+(p.step+1)+'">'+(p.step+1)+" · "+esc(stepName(p.step))+"</a></dd>"+
    "<dt>Status</dt><dd>"+STL[stOf(p)]+"</dd>"+
    "<dt>Item</dt><dd>"+(pid?'<a class="im-tid" href="'+D.part_url.replace("X00000000000-00000",pid)+'">'+esc(pid)+"</a>":'<span class="im-none">'+(k.type?"none yet":"link a type first")+"</span>")+"</dd></dl>"+
    (k.type&&D.plans.indexOf(k.type)>=0?'<a href="'+D.plan_of.replace("X00000000000",k.type)+'">'+esc(k.name)+" plan ▸</a>":"")+"</div>";
}
function renderKinds(){
  var q=$("q").value.trim().toLowerCase(), h="";
  KINDS.forEach(function(k){
    var list=q?k.pos.filter(function(p){return p.name.toLowerCase().indexOf(q)>=0}):k.pos;
    if(q&&!list.length&&k.name.toLowerCase().indexOf(q)<0)return;
    if(q&&!list.length)list=k.pos;
    var op=!!openKind[k.id]||(!!q&&list.length<k.pos.length), inst=k.pos.filter(function(p){return pidOf(p)}).length;
    h+='<div class="im-kind"><div class="im-krow"><button class="im-tog" type="button" data-open="'+k.id+'" aria-expanded="'+op+'" aria-label="Show positions of '+esc(k.name)+'">'+(op?"▾":"▸")+'</button><span class="im-kname">'+esc(k.name)+'</span><span class="im-kcount">'+inst+" / "+k.pos.length+'</span><div class="im-klink">'+
      (k.type?(D.can_edit?'<button class="im-tchip" type="button" data-pick="'+k.id+'" title="Change the linked type">'+k.type+"</button>":'<span class="im-tid">'+k.type+"</span>")+"<span>"+esc(typeName(k.type))+"</span>"
             :'<span class="im-none">no HWDB type</span>'+(D.can_edit?'<button class="btn btn-sm" type="button" data-pick="'+k.id+'">Link type</button>':""))+"</div>";
    if(pickKind===k.id){
      h+='<div class="im-pick"><input type="search" id="im-tq" placeholder="Type name or ID" aria-label="Find a component type"><ul id="im-tlist"></ul>'+(k.type?'<button class="btn btn-sm" type="button" data-unlink="'+k.id+'" style="justify-self:start">Remove link</button>':"")+"</div>";
    }
    h+="</div>";
    if(op){ h+='<ul class="im-plist">'+list.map(function(p){ var st=stOf(p);
      return '<li><button type="button" data-pos="'+p.i+'" aria-current="'+(p.i===sel)+'"><i class="im-dot" style="background:var(--'+(st==="inst"?"good":"surface-2")+')"></i><span>'+esc(p.name)+'</span><span class="im-none">'+(st==="inst"?"installed":"")+"</span></button></li>"; }).join("")+"</ul>"; }
    h+="</div>";
  });
  $("kinds").innerHTML=h||'<p class="im-note" style="padding:8px">No position matches.</p>';
}
/* the type picker: the instant search's types, off the mirror */
var ID=/^[A-Z]\d{11}$/, timer=null;
function fillTypes(){ var el=$("tlist"); if(!el)return; var v=$("tq").value.trim();
  clearTimeout(timer); if(v.length<2){ el.innerHTML=""; return; }
  timer=setTimeout(function(){
    fetch(D.search+"?q="+encodeURIComponent(v),{credentials:"same-origin"}).then(function(r){return r.json()}).then(function(j){
      var ts=j.types||[]; if(!ts.length&&ID.test(v.toUpperCase())) ts=[{part_type_id:v.toUpperCase(),name:""}];
      if(!$("tlist"))return;
      $("tlist").innerHTML=ts.map(function(t){ return '<li><button type="button" data-type="'+t.part_type_id+'" data-n="'+esc(t.name)+'"><span>'+esc(t.name||t.part_type_id)+'</span><span class="im-tid">'+t.part_type_id+"</span></button></li>"; }).join("");
    }).catch(function(){});
  },200); }
function link(kind,type,name){
  var fd=new FormData(); fd.append("action","link"); fd.append("kind",kind); fd.append("type",type);
  fetch(D.page_url,{method:"POST",body:fd,credentials:"same-origin",headers:{"X-CSRFToken":document.querySelector("#im-sync input[name=csrfmiddlewaretoken]").value}}).then(function(r){
    if(!r.ok) throw new Error(r.status);
    KBY[kind].type=type; if(type&&name) D.names[type]=name; pickKind="";
    $("sync").hidden=false; $("synced").hidden=true;
    renderKinds(); renderSel(); readStatus();
  }).catch(function(){ alert("The link was not saved."); });
}
$("kinds").addEventListener("click",function(e){
  var t=e.target.closest("button"); if(!t)return;
  if(t.dataset.open){ openKind[t.dataset.open]=t.getAttribute("aria-expanded")!=="true"; renderKinds(); }
  else if(t.dataset.pick){ pickKind=pickKind===t.dataset.pick?"":t.dataset.pick; renderKinds(); var f=$("tq"); if(f)f.focus(); }
  else if(t.dataset.type){ link(pickKind,t.dataset.type,t.dataset.n); }
  else if(t.dataset.unlink){ link(t.dataset.unlink,"",""); }
  else if(t.dataset.pos){ select(+t.dataset.pos,true); }
});
$("kinds").addEventListener("input",function(e){ if(e.target.id==="im-tq") fillTypes(); });
$("q").addEventListener("input",renderKinds);

/* which linked type's items name which position: one read after the page is up, again after a link changes */
function readStatus(){
  if(!KINDS.some(function(k){return k.type})){ ITEMS={}; statusNote="no kind is linked to a type yet"; dirty=true; showCap(); renderKinds(); return; }
  statusNote="reading HWDB…"; showCap();
  fetch(D.page_url+"?status=1",{credentials:"same-origin"}).then(function(r){return r.json()}).then(function(j){
    ITEMS=j.types||{}; statusNote=(j.failed||[]).length?"not read: "+j.failed.join(", "):"";
  }).catch(function(){ statusNote="HWDB could not be read"; }).then(function(){ dirty=true; showCap(); renderKinds(); renderSel(); });
}

showCap(); renderKinds(); apply(); requestAnimationFrame(frame); readStatus();
})();
