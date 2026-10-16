// Event delegation survives SVG updates; widget disposal removes every listener.
function render({model, el}) {
  el.classList.add('orca-interactive-svg');
  let drag = null;
  const paint = () => {
    el.innerHTML = model.get('value');
    for (const svg of el.querySelectorAll('svg')) {
      svg.style.width = '100%';
      svg.style.height = 'auto';
      svg.style.display = 'block';
    }
  };
  const sendIds = (target) => {
    const item = target.closest('[data-ids]');
    if (item) model.send({action:'select', ids:JSON.parse(item.getAttribute('data-ids'))});
  };
  const click = (event) => {
    if (!event.target.closest('svg[data-energy-min]')) sendIds(event.target);
  };
  const key = (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      if (event.target.closest('[data-ids]')) {
        event.preventDefault();
        sendIds(event.target);
      }
    }
  };
  const coordinate = (event, svg) => {
    const point = svg.createSVGPoint();
    point.x = event.clientX; point.y = event.clientY;
    return point.matrixTransform(svg.getScreenCTM().inverse()).x;
  };
  const energy = (x, svg) => {
    const lo = Number(svg.dataset.energyMin), hi = Number(svg.dataset.energyMax);
    return lo + Math.max(0, Math.min(1, (x-65)/850))*(hi-lo);
  };
  const down = (event) => {
    const svg = event.target.closest('svg[data-energy-min]');
    if (!svg || event.button !== 0) return;
    const x = coordinate(event, svg);
    if (x < 65 || x > 915) return;
    const hit = event.target.closest('[data-ids]');
    drag = {svg, x, start:event.clientX, ids:hit ? JSON.parse(hit.dataset.ids) : null};
    svg.setPointerCapture(event.pointerId);
    event.preventDefault();
  };
  const move = (event) => {
    if (!drag || Math.abs(event.clientX-drag.start) < 6) return;
    if (!drag.rect) {
      drag.rect = document.createElementNS('http://www.w3.org/2000/svg','rect');
      drag.rect.setAttribute('y','35'); drag.rect.setAttribute('height','260');
      drag.rect.setAttribute('fill','#0e7490'); drag.rect.setAttribute('opacity','.15');
      drag.rect.setAttribute('pointer-events','none');
      drag.svg.appendChild(drag.rect);
    }
    const x = Math.max(65, Math.min(915, coordinate(event, drag.svg)));
    drag.rect.setAttribute('x',Math.min(x,drag.x));
    drag.rect.setAttribute('width',Math.abs(x-drag.x));
  };
  const up = (event) => {
    if (!drag) return;
    const current = drag;
    drag = null;
    const end = energy(coordinate(event,current.svg),current.svg);
    if (current.rect) current.rect.remove();
    if (Math.abs(event.clientX-current.start) >= 6) {
      const start = energy(current.x,current.svg);
      model.send({action:'window', lower:Math.min(start,end), upper:Math.max(start,end)});
    } else if (current.ids) {
      model.send({action:'select', ids:current.ids, energy:end});
    } else model.send({action:'energy', energy:end});
  };
  const cancel = () => { if (drag?.rect) drag.rect.remove(); drag = null; };
  paint();
  model.on('change:value',paint);
  el.addEventListener('click',click); el.addEventListener('keydown',key);
  el.addEventListener('pointerdown',down); el.addEventListener('pointermove',move);
  el.addEventListener('pointerup',up); el.addEventListener('pointercancel',cancel);
  return () => {
    model.off('change:value',paint);
    el.removeEventListener('click',click); el.removeEventListener('keydown',key);
    el.removeEventListener('pointerdown',down); el.removeEventListener('pointermove',move);
    el.removeEventListener('pointerup',up); el.removeEventListener('pointercancel',cancel);
    cancel();
  };
}
export default {render};
