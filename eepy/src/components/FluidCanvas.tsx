import React, { useEffect, useRef } from 'react';

interface ZParticle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  char: string;
  size: number;
  alpha: number;
  baseAlpha: number;
  rotation: number;
  rotSpeed: number;
  wobblePhase: number;
  wobbleSpeed: number;
}

export const FluidCanvas: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) return;

    let animId: number;
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    // Mouse tracking
    const mouse = {
      x: -1000,
      y: -1000,
      prevX: -1000,
      prevY: -1000,
      vx: 0,
      vy: 0,
      active: false,
    };

    // Elegant subtle smoky fluid nodes (monochrome / deep slate)
    const blobCount = 6;
    const blobs = Array.from({ length: blobCount }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.3,
      vy: (Math.random() - 0.5) * 0.3,
      radius: Math.random() * 250 + 200,
      alpha: Math.random() * 0.04 + 0.02,
    }));

    // Elegant floating Z glyphs
    const glyphs = ['z', 'Z', 'z', 'zzz', 'z', 'Z'];
    const zCount = Math.min(Math.floor((width * height) / 16000) + 30, 60);
    const zParticles: ZParticle[] = [];

    const createZ = (bottom = false): ZParticle => {
      const char = glyphs[Math.floor(Math.random() * glyphs.length)];
      const size = char === 'zzz' ? 13 : Math.random() * 12 + 13;
      const baseAlpha = Math.random() * 0.3 + 0.15; // subtle, not glaring

      return {
        x: Math.random() * width,
        y: bottom ? height + 20 : Math.random() * height,
        vx: (Math.random() - 0.5) * 0.25,
        vy: -(Math.random() * 0.4 + 0.2), // calm upward drift
        char,
        size,
        alpha: baseAlpha,
        baseAlpha,
        rotation: (Math.random() - 0.5) * 0.3,
        rotSpeed: (Math.random() - 0.5) * 0.005,
        wobblePhase: Math.random() * Math.PI * 2,
        wobbleSpeed: Math.random() * 0.015 + 0.008,
      };
    };

    for (let i = 0; i < zCount; i++) {
      zParticles.push(createZ(false));
    }

    const handleResize = () => {
      if (!canvas) return;
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    };

    const handlePointerMove = (e: MouseEvent | TouchEvent) => {
      mouse.active = true;
      const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX;
      const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY;
      mouse.x = clientX;
      mouse.y = clientY;
    };

    const handlePointerLeave = () => {
      mouse.active = false;
    };

    window.addEventListener('resize', handleResize);
    window.addEventListener('mousemove', handlePointerMove);
    window.addEventListener('touchmove', handlePointerMove, { passive: true });
    window.addEventListener('mouseleave', handlePointerLeave);

    let time = 0;

    const render = () => {
      time += 0.005;

      // Mouse velocity
      if (mouse.prevX !== -1000) {
        mouse.vx = (mouse.x - mouse.prevX) * 0.2;
        mouse.vy = (mouse.y - mouse.prevY) * 0.2;
      }
      mouse.prevX = mouse.x;
      mouse.prevY = mouse.y;

      // Minimalist deep pitch dark background
      ctx.fillStyle = '#08080a';
      ctx.fillRect(0, 0, width, height);

      // --- Subtle, elegant smoky fluid blobs in the background ---
      for (let i = 0; i < blobs.length; i++) {
        const b = blobs[i];
        b.x += b.vx + Math.sin(time + i) * 0.2;
        b.y += b.vy + Math.cos(time + i * 1.3) * 0.2;

        if (b.x < -b.radius) b.x = width + b.radius;
        if (b.x > width + b.radius) b.x = -b.radius;
        if (b.y < -b.radius) b.y = height + b.radius;
        if (b.y > height + b.radius) b.y = -b.radius;

        const grad = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.radius);
        grad.addColorStop(0, `rgba(255, 255, 255, ${b.alpha})`);
        grad.addColorStop(1, 'rgba(255, 255, 255, 0)');

        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(b.x, b.y, b.radius, 0, Math.PI * 2);
        ctx.fill();
      }

      // --- Floating Z particles (pure typography, mouse reactive) ---
      for (let i = 0; i < zParticles.length; i++) {
        const p = zParticles[i];

        // Calm upward float with gentle wobble
        p.wobblePhase += p.wobbleSpeed;
        p.x += p.vx + Math.sin(p.wobblePhase) * 0.3;
        p.y += p.vy;
        p.rotation += p.rotSpeed;

        // Friction
        p.vx *= 0.98;
        p.vy = p.vy * 0.99 - 0.003;

        // Smooth mouse reaction (gentle repulsion & drift)
        if (mouse.active) {
          const dx = p.x - mouse.x;
          const dy = p.y - mouse.y;
          const dist = Math.hypot(dx, dy);
          const reach = 160;

          if (dist < reach && dist > 0) {
            const force = (1 - dist / reach) * 2.2;
            p.vx += (dx / dist) * force + mouse.vx * 0.08;
            p.vy += (dy / dist) * force + mouse.vy * 0.08;
            p.alpha = Math.min(0.7, p.alpha + 0.05);
          }
        }

        // Return to base alpha
        p.alpha += (p.baseAlpha - p.alpha) * 0.01;

        // Wrap around screen
        if (p.y < -30) {
          p.y = height + 20;
          p.x = Math.random() * width;
          p.vy = -(Math.random() * 0.4 + 0.2);
          p.vx = (Math.random() - 0.5) * 0.25;
        }
        if (p.x < -30) p.x = width + 30;
        if (p.x > width + 30) p.x = -30;

        // Draw clean monochrome Z glyph
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rotation);
        ctx.font = `500 ${p.size}px 'JetBrains Mono', monospace`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#f4f4f5';
        ctx.globalAlpha = p.alpha;
        ctx.fillText(p.char, 0, 0);
        ctx.restore();
      }

      animId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('mousemove', handlePointerMove);
      window.removeEventListener('touchmove', handlePointerMove);
      window.removeEventListener('mouseleave', handlePointerLeave);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      id="fluid-canvas"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100vh',
        pointerEvents: 'none',
        zIndex: 0,
      }}
    />
  );
};
