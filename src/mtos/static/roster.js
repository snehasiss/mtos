'use strict';
const $=s=>document.querySelector(s), form=$('#asset-form');
let schema,current=null,offset=0,searchGeneration=0;
const field=n=>form.elements.namedItem(n);
const val=n=>field(n).value.trim()||null;
function error(e){const box=$('#error');box.textContent=e.message;box.scrollIntoView({block:'center'});}
async function api(path,options={}){
 const headers={'X-CSRF-Token':$('meta[name="csrf-token"]').content,...options.headers};
 if(options.body && !(options.body instanceof FormData)) headers['Content-Type']='application/json';
 const response=await fetch(path,{...options,headers});const data=await response.json();
 if(!response.ok)throw Error(data.error||'Request failed'); return data;
}
function option(select,value,label=value){const o=document.createElement('option');o.value=value;o.textContent=label;select.append(o);}
function types(value){field('type').replaceChildren();schema.families[field('family').value].forEach(t=>option(field('type'),t));if(value)field('type').value=value;}
function title(asset){const p=asset.prototype||{};return [p.reporting_mark,p.road_number].filter(Boolean).join(' ')||asset.label||asset.id;}
async function load(){
 const generation=++searchGeneration;
 const query=new URLSearchParams({q:$('#search').value,family:$('#filter-family').value,status:$('#filter-status').value,offset,limit:24});
 const result=await api('/api/assets?'+query);if(generation!==searchGeneration)return;
 $('#cards').replaceChildren();$('#summary').textContent=`${result.total} assets · ${result.total ? offset+1 : 0}–${Math.min(offset+24,result.total)}`;
 $('#previous').disabled=offset===0;$('#next').disabled=offset+24>=result.total;
 for(const asset of result.items){
  const card=document.createElement('button');card.className='card';card.onclick=()=>edit(asset.id).catch(error);
  const media=asset.media.images;
  if(media.length){const img=document.createElement('img');img.src=asset.media.base_url+media[0].filename;img.alt=title(asset);img.loading='lazy';card.append(img);}
  else{const empty=document.createElement('div');empty.className='placeholder';empty.textContent=asset.id;card.append(empty);}
  const body=document.createElement('div');body.className='body';
  const top=document.createElement('div');top.className='card-top';
  const name=document.createElement('strong');name.textContent=title(asset);top.append(name);
  const badge=document.createElement('span');badge.className='badge';badge.textContent=asset.lifecycle.status||asset.lifecycle.possession;top.append(badge);body.append(top);
  const meta=document.createElement('p');meta.className='meta';
  const assetId=document.createElement('span');assetId.className='asset-id';assetId.textContent=asset.id;
  const classification=document.createElement('span');classification.textContent=` · ${asset.family} · ${asset.type}`;meta.append(assetId,classification);body.append(meta);
  const builder=document.createElement('p');builder.className='builder-model';builder.textContent=[asset.prototype?.maker,asset.prototype?.model].filter(Boolean).join(' · ');body.append(builder);
  card.append(body);$('#cards').append(card);
 }
}
async function edit(id){
 current=id?await api('/api/assets/'+id):null;form.reset();$('#error').textContent='';$('#save-status').textContent='';
 const a=current||{},p=a.prototype||{},m=a.model||{},l=a.lifecycle||{},c=a.control||{};
 field('family').value=a.family||'loco';types(a.type);field('id').readOnly=true;
 const values={id:a.id,label:a.label,reporting_mark:p.reporting_mark,road_number:p.road_number,prototype_maker:p.maker,prototype_model:p.model,
 scale:m.scale,model_maker:m.maker,product_number:m.product_number,catalog_name:m.catalog_name,
 possession:l.possession||'planned',status:l.status||'unavailable',location:l.location||'off_track',purchased_on:l.purchased_on,
 source:l.acquisition?.source,price:l.acquisition?.price,address:c.address,decoder_maker:c.decoder?.maker,decoder_model:c.decoder?.model,node_id:c.node_id,notes:a.notes};
 for(const [k,v] of Object.entries(values))field(k).value=v??'';
 if(!id)field('id').value=(await api('/api/next-asset-id?family='+encodeURIComponent(field('family').value))).id;
 field('dcc').checked=c.dcc===true;field('sound').checked=c.sound===true;
 $('#editor-title').textContent=id?title(a):'Add asset';$('#library').hidden=true;$('#editor').hidden=false;$('#photos').hidden=!id;
 gallery();window.scrollTo(0,0);
}
function gallery(){
 $('#gallery').replaceChildren();if(!current)return;
 for(const photo of current.media.images){const a=document.createElement('a');a.href=current.media.base_url+photo.filename;a.target='_blank';a.rel='noopener';
 const img=document.createElement('img');img.src=a.href;img.alt=photo.filename;img.loading='lazy';a.append(img);$('#gallery').append(a);}
}
form.onsubmit=async e=>{e.preventDefault();$('#error').textContent='';const button=form.querySelector('button[type="submit"]');button.disabled=true;
 try{
 if(current&&current.lifecycle?.status==='active'&&val('status')!=='active'){
  const op=await api('/api/assets/'+current.id+'/operation');
  if((op.leased||op.reserved)&&!confirm(current.id+' is under operational control. Changing its status releases it: Core will refuse throttle and function commands, and a moving locomotive keeps its last speed. Stop it first if needed. Continue?'))return;
 }
 if(current&&current.control?.dcc===true&&Number(val('address'))!==current.control.address){
  if(!confirm('Changing the roster DCC address does not program the physical decoder. Use MTOS Programming for a coordinated decoder address change. Save this inventory-only change anyway?'))return;
 }
 const payload={id:current?.id||val('id'),family:val('family'),type:val('type'),label:val('label'),notes:val('notes'),
 prototype:{...(current?.prototype||{}),reporting_mark:val('reporting_mark'),road_number:val('road_number'),maker:val('prototype_maker'),model:val('prototype_model')},
 model:{...(current?.model||{}),scale:val('scale'),maker:val('model_maker'),product_number:val('product_number'),catalog_name:val('catalog_name')},
 lifecycle:{...(current?.lifecycle||{}),possession:val('possession'),status:val('status'),location:val('location'),purchased_on:val('purchased_on'),
 acquisition:{...(current?.lifecycle?.acquisition||{}),source:val('source'),price:val('price')===null?null:Number(val('price'))}},
 components:current?.components||[],relations:current?.relations||[]};
 payload.control=field('dcc').checked?{...(current?.control||{}),dcc:true,node_id:null,address:val('address')?Number(val('address')):null,
 decoder:{...(current?.control?.decoder||{}),maker:val('decoder_maker'),model:val('decoder_model')},sound:field('sound').checked}
 :{dcc:null,address:null,decoder:null,speed_steps:null,sound:null,node_id:val('node_id'),attributes:current?.control?.attributes||{}};
 if(current)payload.revision=current.revision;
 const result=await api('/api/assets'+(current?'/'+current.id:''),{method:current?'PATCH':'POST',body:JSON.stringify(payload)});
 await edit(result.id);$('#save-status').textContent='Saved';
 }catch(e){error(e);}finally{button.disabled=false;}};
$('#image-form').onsubmit=async e=>{e.preventDefault();try{
 const data=new FormData(e.target);data.set('sequence',Math.max(0,...current.media.images.map(i=>i.sequence))+1);
 await api(`/api/assets/${current.id}/media`,{method:'POST',body:data});current=await api('/api/assets/'+current.id);gallery();e.target.reset();
 }catch(e){error(e);}};
async function loadConsists(){const result=await api('/api/consists');$('#consists').replaceChildren();for(const c of result.items){const b=document.createElement('button');b.className='secondary';b.textContent=`${c.id} · ${c.label||''} · ${c.units.join(' → ')}`;b.onclick=()=>{for(const n of ['id','label','revision'])$('#consist-form').elements[n].value=c[n]??'';$('#consist-form').elements.units.value=c.units.join(', ');};$('#consists').append(b);}}
$('#consist-form').onsubmit=async e=>{e.preventDefault();try{const data=Object.fromEntries(new FormData(e.target));data.units=data.units.split(',').map(x=>x.trim()).filter(Boolean);const update=!!data.revision;if(update)data.revision=Number(data.revision);else delete data.revision;await api('/api/consists'+(update?'/'+data.id:''),{method:update?'PATCH':'POST',body:JSON.stringify(data)});e.target.reset();await loadConsists();}catch(e){error(e);}};
$('#new-consist').onclick=()=>$('#consist-form').reset();
$('#add').onclick=()=>edit().catch(error);$('#back').onclick=()=>{$('#editor').hidden=true;$('#library').hidden=false;$('#error').textContent='';load().catch(error);};
field('family').onchange=()=>{types();if(!current)api('/api/next-asset-id?family='+encodeURIComponent(field('family').value)).then(result=>field('id').value=result.id).catch(error);};
field('possession').onchange=()=>{field('status').value=val('possession')==='received'?'stored':'unavailable';};
$('#previous').onclick=()=>{offset=Math.max(0,offset-24);load().catch(error);};$('#next').onclick=()=>{offset+=24;load().catch(error);};
let timer;for(const s of ['#search','#filter-family','#filter-status'])$(s).addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>{offset=0;load().catch(error);},180);});
(async()=>{schema=await api('/api/schema');for(const family of Object.keys(schema.families)){option(field('family'),family);option($('#filter-family'),family);}schema.possession.forEach(p=>option(field('possession'),p));schema.status.forEach(s=>{option(field('status'),s);option($('#filter-status'),s);});schema.locations.forEach(location=>option(field('location'),location));await load();await loadConsists();})().catch(error);
