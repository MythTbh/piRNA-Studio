// Compact decorative RNA strand. Styles travel with the illustration.
(() => {
  let release = () => {};
  const mountRna = () => {
    const intro = document.querySelector('#main .intro');
    if (intro?.querySelector('.rna-art')) return;
    release();
    if (!intro) return;
    if (!document.getElementById('rna-illustration-style')) {
      const style = document.createElement('style');
      style.id = 'rna-illustration-style';
      style.textContent = `
        #main .intro { position:relative; isolation:isolate; padding-right:32%; min-height:0; }
        #main .intro > :not(.rna-art) { position:relative; z-index:1; }
        .rna-art { position:absolute; right:0; top:calc(-1 * var(--rna-header-offset,35px)); bottom:0; width:65%; max-width:none; height:auto; pointer-events:none; z-index:0; overflow:hidden; -webkit-mask-image:linear-gradient(to right,rgba(0,0,0,.08),rgba(0,0,0,.2) 30%,#000 68%); mask-image:linear-gradient(to right,rgba(0,0,0,.08),rgba(0,0,0,.2) 30%,#000 68%); }
        .rna-art svg { display:block; width:100%; height:100%; overflow:hidden; }
        @media(max-width:640px) { #main .intro { padding-right:0; } .rna-art { position:relative; right:auto; top:auto; bottom:auto; width:210px; height:140px; margin:8px auto 0; -webkit-mask-image:none; mask-image:none; } }
      `;
      document.head.append(style);
    }
    const art=document.createElement('div');
    art.className='rna-art';
    art.setAttribute('aria-hidden','true');
    art.innerHTML=`<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200" viewBox="-140 -80 450 300" preserveAspectRatio="xMidYMin slice" fill="none" focusable="false"><defs><radialGradient id="rna-ambient"><stop stop-color="#d6e5d4" stop-opacity=".55"/><stop offset="1" stop-color="#d6e5d4" stop-opacity="0"/></radialGradient></defs><ellipse cx="150" cy="100" rx="142" ry="78" fill="url(#rna-ambient)"/><g class="rna-ribbon" transform="rotate(28 150 100)"></g></svg>`;
    intro.append(art);
    const layer=art.querySelector('.rna-ribbon');
    const fitHeader=()=> {
      const header=document.querySelector('#top');
      if(header) {
        const offset=Math.max(0,intro.getBoundingClientRect().top-header.getBoundingClientRect().bottom);
        art.style.setProperty('--rna-header-offset',`${offset}px`);
      }
    };
    fitHeader();
    const resizeObserver=new ResizeObserver(fitHeader);
    resizeObserver.observe(intro);
    const header=document.querySelector('#top');
    if(header) resizeObserver.observe(header);
    const ns='http://www.w3.org/2000/svg';
    const makePath=()=> {
      const node=document.createElementNS(ns,'path');
      node.setAttribute('stroke-linejoin','round');
      layer.append(node);
      return node;
    };
    // A broad, paper-thin ribbon with a softly lit face and a fine reverse edge.
    const rings=168,sides=8;
    const faces=Array.from({length:rings*sides},(_,i)=>({node:makePath(),ring:Math.floor(i/sides),side:i%sides}));
    const colors=[[120,145,123],[164,170,140],[146,156,145],[183,174,149]];
    const bases=Array.from({length:36},(_,i)=>({node:makePath(),shine:makePath(),t:-1+(i+.5)/36*2.2,color:colors[i%4]}));
    const project=p=> {
      const scale=460/(460-p.z);
      return {x:150+p.x*scale,y:100+p.y*scale,z:p.z};
    };
    const center=(t,phase)=> {
      const angle=t*Math.PI*4.2+phase;
      return {x:(t-.5)*280,y:Math.cos(angle)*37,z:Math.sin(angle)*37,angle};
    };
    const polygon=points=>'M'+points.map(p=>`${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' L')+' Z';
    const shade=(rgb,light,specular=0)=>`rgb(${rgb.map(c=>Math.min(255,Math.round(c*light+specular))).join(',')})`;
    const vertex=(t,phase,theta)=> {
      const c=center(t,phase), a=c.angle;
      // A very thin elliptical cross section gives the ribbon width without tubular bulk.
      const pitch=37*Math.PI*4.2, norm=Math.hypot(280,pitch);
      const radial={x:0,y:Math.cos(a),z:Math.sin(a)};
      const binormal={x:-pitch/norm,y:-280*Math.sin(a)/norm,z:280*Math.cos(a)/norm};
      const taper=.92+.08*Math.pow(Math.abs(Math.sin(Math.PI*t)),.4);
      const halfWidth=9*taper, halfThickness=.42;
      const along=Math.sin(theta)*halfWidth, across=Math.cos(theta)*halfThickness;
      const raw={x:radial.x*Math.cos(theta)/halfThickness+binormal.x*Math.sin(theta)/halfWidth,y:radial.y*Math.cos(theta)/halfThickness+binormal.y*Math.sin(theta)/halfWidth,z:radial.z*Math.cos(theta)/halfThickness+binormal.z*Math.sin(theta)/halfWidth};
      const length=Math.hypot(raw.x,raw.y,raw.z);
      const n={x:raw.x/length,y:raw.y/length,z:raw.z/length};
      return {point:project({x:c.x+radial.x*across+binormal.x*along,y:c.y+radial.y*across+binormal.y*along,z:c.z+radial.z*across+binormal.z*along}),normal:n};
    };
    const draw=phase=> {
      const ordered=[];
      layer.setAttribute('transform',`rotate(${28+2*Math.sin(phase*.5)} 150 100)`);
      // Shared vertices keep the fine ribbon edges continuous through each turn.
      const mesh=Array.from({length:rings+1},(_,r)=>Array.from({length:sides+1},(_,s)=>vertex(-1+r/rings*2.2,phase,s/sides*Math.PI*2)));
      for(const item of faces) {
        const r=item.ring,s=item.side;
        const vertices=[mesh[r][s],mesh[r+1][s],mesh[r+1][s+1],mesh[r][s+1]];
        const n=vertices[0].normal;
        const diffuse=Math.max(0,-.35*n.x-.55*n.y+.76*n.z);
        const specular=Math.pow(Math.max(0,-.15*n.x-.30*n.y+.94*n.z),10)*25;
        const fill=shade([112,141,116],.52+.43*diffuse,specular);
        item.node.setAttribute('d',polygon(vertices.map(v=>v.point)));
        item.node.setAttribute('fill',fill);
        item.node.setAttribute('stroke',fill);
        item.node.setAttribute('stroke-width','.2');
        ordered.push({node:item.node,z:vertices.reduce((sum,v)=>sum+v.point.z,0)/4});
      }
      for(const item of bases) {
        const c=center(item.t,phase);
        const a=project(c),b=project({x:c.x,y:c.y*.12,z:c.z*.12});
        const d=`M${a.x},${a.y} L${b.x},${b.y}`;
        const light=.60+.4*(c.z/37+1)/2;
        item.node.setAttribute('d',d);
        item.node.setAttribute('fill','none');
        item.node.setAttribute('stroke',shade(item.color,light));
        item.node.setAttribute('stroke-width',String(3.6*(1+c.z/460)));
        item.node.setAttribute('stroke-linecap','round');
        item.shine.setAttribute('d',`M${a.x-.8},${a.y-1} L${b.x-.8},${b.y-1}`);
        item.shine.setAttribute('fill','none');
        item.shine.setAttribute('stroke','#edf2df');
        item.shine.setAttribute('stroke-opacity','.24');
        item.shine.setAttribute('stroke-width','.7');
        item.shine.setAttribute('stroke-linecap','round');
        const depth=c.z*.56;
        ordered.push({node:item.node,z:depth},{node:item.shine,z:depth+.01});
      }
      ordered.sort((a,b)=>a.z-b.z);
      ordered.forEach(({node},i)=>{if(layer.children[i]!==node) layer.insertBefore(node,layer.children[i]||null);});
    };
    const preference=window.matchMedia('(prefers-reduced-motion: reduce)');
    const scrollPhase=()=>.45+Math.max(0,window.scrollY||0)*.018;
    let frame=0,last=0,phase=scrollPhase(),target=phase;
    const tick=time=> {
      frame=0;
      if(!art.isConnected || preference.matches || document.hidden) return;
      if(time-last>=1000/30) {
        last=time;
        phase+=(target-phase)*.22;
        if(Math.abs(target-phase)<.001) phase=target;
        draw(phase);
      }
      if(phase!==target) frame=requestAnimationFrame(tick);
    };
    const onScroll=()=> {
      target=scrollPhase();
      if(!preference.matches && !frame && !document.hidden) frame=requestAnimationFrame(tick);
    };
    const syncMotion=()=> {
      cancelAnimationFrame(frame);
      frame=0;
      target=scrollPhase();
      // Reduced motion keeps a still illustration, including while scrolling.
      if(preference.matches) {phase=.45;draw(phase);}
      else {phase=target;draw(phase);}
    };
    const onVisibility=()=> {if(!document.hidden) onScroll();};
    window.addEventListener('scroll',onScroll,{passive:true});
    document.addEventListener('visibilitychange',onVisibility);
    preference.addEventListener('change',syncMotion);
    release=()=> {
      resizeObserver.disconnect();
      cancelAnimationFrame(frame);
      window.removeEventListener('scroll',onScroll);
      document.removeEventListener('visibilitychange',onVisibility);
      preference.removeEventListener('change',syncMotion);
    };
    syncMotion();
  };
  const main=document.querySelector('#main');
  if(main) {mountRna();new MutationObserver(mountRna).observe(main,{childList:true});}
})();







