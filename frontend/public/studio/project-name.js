/* One display-name rule for the spatial studio and its linked Chat. */
globalThis.shortStudioName=function(name,notes=[],shots=[]){
  const clean=value=>String(value||'').replace(/\s*[·-]\s*(创作方案|创意方案|方案)\s*$/,'').trim();
  const readable=value=>value&&!/^[a-f\d]{24,}(?:\.[a-z\d]+)?$/i.test(value)&&!/^\d{4}[-/]\d/.test(value);
  const candidates=[clean(name),...notes.map(n=>clean(n.title)),...shots.map(s=>clean(s.name))];
  return candidates.find(readable)||'未命名画布';
};
