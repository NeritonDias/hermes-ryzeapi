// Synthetic browser harness. Nothing in this file is loaded by the live dashboard.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { Button } from '@nous-research/ui/ui/components/button';
import { Input } from '@nous-research/ui/ui/components/input';
import { Label } from '@nous-research/ui/ui/components/label';
let state = {credential_saved:false,credential_kind:'account',instance:'',allowed_users:'',allowed_recipients:'',enabled:false,runtime_running:false,webhook_configured:false,buffer_seconds:10,echo_transcripts:true};
let status = 'disconnected';
let instances = [];
window.testSeed = value => { Object.assign(state,value); if(state.instance && !instances.includes(state.instance)) instances.push(state.instance); };
window.testStateFailures = 0;
window.testCalls = [];
window.testConnected = () => { status='connected'; };
window.testReject = false;
window.testTransport = {running:true,consumer_healthy:true,websocket_connected:true,whatsapp_state:'connected',buffer_pending:0,stt_waiting:0,delivery_counts:{},review_items:[]};
window.testTransportError = false;
window.testGroups = [];
window.testGroupFailure = false;
const item = name => ({name,status,number:'5511999999999',profile_name:'CONTA SINTÉTICA'});
window.__HERMES_PLUGIN_SDK__ = {React, components:{Button,Input,Label}, fetchJSON: async (url, init={}) => {
  const path=url.replace('/api/plugins/ryzeapi','');
  const data=init.body ? JSON.parse(init.body) : {};
  window.testCalls.push({path,method:init.method || 'GET',data});
  if (path.startsWith('/groups')) {
    if (window.testGroupFailure) throw Object.assign(new Error('Group failure'), {body:'{"detail":"Sincronização indisponível. O catálogo anterior foi preservado."}'});
    if (path === '/groups/sync') window.testGroups = [
      ...window.testGroups, ...(!window.testGroups.length ? [{jid:'120363000000000001@g.us',name:'Família · exemplo sintético',members:8,present:1,synced:1789488000,mode:'blocked',trigger:'mentions',senders:'authorized'}] : [])];
    if (path === '/groups/policy') window.testGroups = window.testGroups.map(row => row.jid === data.jid ? {...row,mode:data.mode,trigger:data.trigger,senders:data.senders} : row);
    return {instance:state.instance,groups:window.testGroups.map(row=>({...row}))};
  }
  if (path==='/state') { if(window.testStateFailures-- > 0) throw new Error('Synthetic state failure'); return {...state}; }
  if (path==='/transport') { if (window.testTransportError) throw new Error('Synthetic unavailable'); return {...window.testTransport}; }
  if (path==='/account') {
    if (window.testReject) throw Object.assign(new Error('Token recusado'), {status:400,body:'{"detail":"Token recusado pela RyzeAPI. Confira a credencial atual."}'});
    state.credential_saved=true; state.credential_kind=data.kind; return {instances:instances.map(item)};
  }
  if (path==='/instances' && init.method==='POST') { instances.push(data.name); state.instance=data.name; return {instance:item(data.name)}; }
  if (path==='/instances') return {instances:instances.map(item)};
  if (path==='/select') {state.instance=data.name; return {instance:item(data.name)};}
  if (path==='/connect') return data.number ? {pairing_code:'ABCD-EFGH',expires_in:60,status:'pairing'} :
    {qr:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXuoAAAAASUVORK5CYII=',expires_in:20,status:'qr'};
  if (path==='/connection') return {instance:item(state.instance)};
  if (path==='/activate') {Object.assign(state,{enabled:true,runtime_running:true,webhook_configured:true,allowed_users:data.allowed_users,allowed_recipients:data.allowed_recipients}); return {...state};}
  if (path==='/firewall') {Object.assign(state,{allowed_users:data.allowed_users,allowed_recipients:data.allowed_recipients});return {saved:true,...state};}
  if (path==='/buffer') {state.buffer_seconds=data.buffer_seconds;return {saved:true,buffer_seconds:state.buffer_seconds};}
  if (path==='/transcription') {state.echo_transcripts=data.echo_transcripts;return {saved:true,echo_transcripts:state.echo_transcripts};}
  if (path==='/pause') {state.enabled=false;state.runtime_running=false;return {...state};}
  if (path==='/forget') {state={credential_saved:false,enabled:false};return {...state};}
  throw new Error('Unexpected mock API call');
}};
window.__HERMES_PLUGINS__ = {register: (name, App) => createRoot(document.getElementById('root')).render(<App/>)};
