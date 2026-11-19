(()=>{
 const panel=document.getElementById('menu-panel');
 if(!panel)return;
 const scrim=document.getElementById('menu-scrim');
 const categories=[...document.querySelectorAll('.nav-category')];
 const close=()=>{panel.hidden=true;scrim.hidden=true;document.body.classList.remove('menu-open');categories.forEach(x=>x.setAttribute('aria-expanded','false'));};
 categories.forEach(btn=>btn.addEventListener('click',()=>{
  const section=document.getElementById(btn.dataset.menu);if(!section)return;
  const same=!panel.hidden&&!section.hidden;
  close();if(same)return;
  panel.querySelectorAll('.menu-section').forEach(x=>x.hidden=x!==section);
  document.getElementById('menu-title').textContent=section.dataset.title;
  panel.hidden=false;scrim.hidden=false;document.body.classList.add('menu-open');
  btn.setAttribute('aria-expanded','true');document.getElementById('menu-close').focus();
 }));
 document.getElementById('menu-close').addEventListener('click',close);
 scrim.addEventListener('click',close);
 document.addEventListener('keydown',e=>{if(e.key==='Escape')close()});
 panel.querySelectorAll('a').forEach(x=>x.addEventListener('click',close));
})();
