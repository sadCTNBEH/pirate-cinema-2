/**
 * @file components/ui/NavIcons.tsx
 * @description Векторные и канвас иконки для навигационного меню.
 * Включает настоящий 4D-тессеракт для Главной, вращающийся одновременно
 * в трёх пространственных осях (X, Y, Z) с гиперпространственной проекцией,
 * терминальную иконку для Библиотеки и квантовый реактор для Настроек.
 */

import React, { useEffect, useRef } from 'react';

interface NavIconProps {
  className?: string;
  active?: boolean;
}

// 16 вершин 4D-гиперкуба (тессеракта) с координатами (±1, ±1, ±1, ±1)
const TESSERACT_VERTICES: [number, number, number, number][] = [];
for (let i = 0; i < 16; i++) {
  TESSERACT_VERTICES.push([
    (i & 1) ? 1 : -1,
    (i & 2) ? 1 : -1,
    (i & 4) ? 1 : -1,
    (i & 8) ? 1 : -1,
  ]);
}

// 32 ребра тессеракта (соединяют вершины, отличающиеся ровно на 1 координату)
const TESSERACT_EDGES: [number, number][] = [];
for (let i = 0; i < 16; i++) {
  for (let j = i + 1; j < 16; j++) {
    let diff = 0;
    for (let k = 0; k < 4; k++) {
      if (TESSERACT_VERTICES[i][k] !== TESSERACT_VERTICES[j][k]) diff++;
    }
    if (diff === 1) {
      TESSERACT_EDGES.push([i, j]);
    }
  }
}

/**
 * Иконка Главной страницы: Настоящий 4D-Тессеракт, вращающийся в трёх осях (X, Y, Z).
 * Полноценная 3D/4D перспективная проекция с 16 вершинами и 32 ребрами.
 */
export const NavCatalogIcon: React.FC<NavIconProps> = ({ className = '', active = false }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const size = 24;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    let angleX = 0.55;
    let angleY = 0.65;
    let angleZ = 0.35;
    let angleW = 0.45;
    let animId: number;

    const render = () => {
      ctx.clearRect(0, 0, size, size);

      if (active) {
        angleX += 0.0042;
        angleY += 0.0062;
        angleZ += 0.0032;
        angleW += 0.0048;
      }

      const cx = size / 2;
      const cy = size / 2;
      const scale = size * 1.05;

      const cosX = Math.cos(angleX), sinX = Math.sin(angleX);
      const cosY = Math.cos(angleY), sinY = Math.sin(angleY);
      const cosZ = Math.cos(angleZ), sinZ = Math.sin(angleZ);
      const cosW = Math.cos(angleW), sinW = Math.sin(angleW);

      const projected: [number, number, number][] = [];

      for (let i = 0; i < 16; i++) {
        const [x, y, z, w] = TESSERACT_VERTICES[i];

        const y1 = y * cosX - z * sinX;
        const z1 = y * sinX + z * cosX;

        const x2 = x * cosY + z1 * sinY;
        const z2 = -x * sinY + z1 * cosY;

        const x3 = x2 * cosZ - y1 * sinZ;
        const y3 = x2 * sinZ + y1 * cosZ;

        const x4 = x3 * cosW - w * sinW;
        const w4 = x3 * sinW + w * cosW;

        const d4 = 2.6;
        const p4 = 1 / (d4 - w4);
        const x3d = x4 * p4;
        const y3d = y3 * p4;
        const z3d = z2 * p4;

        const d3 = 3.0;
        const p3 = 1 / (d3 - z3d);
        const px = cx + x3d * p3 * scale;
        const py = cy + y3d * p3 * scale;

        projected.push([px, py, p3]);
      }

      ctx.lineWidth = 1.15;
      for (let e = 0; e < TESSERACT_EDGES.length; e++) {
        const [i, j] = TESSERACT_EDGES[e];
        const [x1, y1, depth1] = projected[i];
        const [x2, y2, depth2] = projected[j];

        const avgDepth = (depth1 + depth2) / 2;
        ctx.strokeStyle = active
          ? `rgba(0, 240, 255, ${Math.min(1, Math.max(0.35, avgDepth * 2))})`
          : `rgba(148, 163, 184, ${Math.min(0.85, Math.max(0.25, avgDepth * 1.5))})`;

        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }

      ctx.fillStyle = active ? '#ffffff' : '#cbd5e1';
      for (let i = 0; i < 16; i++) {
        const [px, py] = projected[i];
        ctx.fillRect(px - 0.75, py - 0.75, 1.5, 1.5);
      }

      if (active) {
        animId = requestAnimationFrame(render);
      }
    };

    render();

    return () => {
      if (animId) cancelAnimationFrame(animId);
    };
  }, [active]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: 22, height: 22 }}
      className={`inline-block select-none pointer-events-none transition-all duration-300 ${className}`}
    />
  );
};

export const NavSearchIcon: React.FC<NavIconProps> = ({ className = '', active = false }) => {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`transition-all duration-300 ${className}`}
    >
      <circle
        cx="11"
        cy="11"
        r="8"
        stroke={active ? '#00f0ff' : 'currentColor'}
        strokeWidth="1.6"
        fill={active ? 'rgba(0, 240, 255, 0.08)' : 'none'}
      />
      <circle
        cx="11"
        cy="11"
        r="4.5"
        stroke={active ? '#38bdf8' : 'currentColor'}
        strokeWidth="1"
        strokeOpacity={active ? 0.8 : 0.5}
      />
      <circle cx="11" cy="11" r="1.5" fill={active ? '#00f0ff' : 'currentColor'} />

      <g className={active ? 'origin-[11px_11px] animate-[spin_4s_linear_infinite]' : ''}>
        <line
          x1="11"
          y1="11"
          x2="17.5"
          y2="6"
          stroke={active ? '#38bdf8' : 'currentColor'}
          strokeWidth="1.6"
          strokeLinecap="round"
        />
        <circle cx="17.5" cy="6" r="1.5" fill={active ? '#ffffff' : 'currentColor'} />
      </g>

      <path
        d="M16.8 16.8L20.5 20.5"
        stroke={active ? '#00f0ff' : 'currentColor'}
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  );
};

export const NavLibraryIcon: React.FC<NavIconProps> = ({ className = '', active = false }) => {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`transition-all duration-300 ${className}`}
    >
      <rect
        x="2.5"
        y="4"
        width="19"
        height="15"
        rx="2.5"
        stroke={active ? '#00f0ff' : 'currentColor'}
        strokeWidth="1.6"
        fill={active ? 'rgba(0, 240, 255, 0.08)' : 'none'}
      />
      <path
        d="M2.5 8H21.5"
        stroke={active ? '#38bdf8' : 'currentColor'}
        strokeWidth="1"
        strokeOpacity={active ? 0.7 : 0.4}
      />
      <circle cx="5.5" cy="6" r="0.9" fill={active ? '#00f0ff' : 'currentColor'} />
      <circle cx="8" cy="6" r="0.9" fill={active ? '#38bdf8' : 'currentColor'} />
      <path
        d="M6 11.5L8.5 13.5L6 15.5"
        stroke={active ? '#00f0ff' : 'currentColor'}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect
        x="10.5"
        y="14.5"
        width="4"
        height="1.5"
        fill={active ? '#00f0ff' : 'currentColor'}
        className={active ? 'animate-[pulse_1s_steps(2,start)_infinite]' : ''}
      />
      <path
        d="M8.5 20.5H15.5"
        stroke={active ? '#00f0ff' : 'currentColor'}
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
};

export const NavSettingsIcon: React.FC<NavIconProps> = ({ className = '', active = false }) => {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`transition-all duration-300 ${className}`}
    >
      <g className={active ? 'origin-center animate-[spin_8s_linear_infinite]' : ''}>
        <circle
          cx="12"
          cy="12"
          r="8.5"
          stroke={active ? '#00f0ff' : 'currentColor'}
          strokeWidth="1.5"
        />
        <line x1="12" y1="2.5" x2="12" y2="4.5" stroke={active ? '#00f0ff' : 'currentColor'} strokeWidth="1.8" strokeLinecap="round" />
        <line x1="12" y1="19.5" x2="12" y2="21.5" stroke={active ? '#00f0ff' : 'currentColor'} strokeWidth="1.8" strokeLinecap="round" />
        <line x1="2.5" y1="12" x2="4.5" y2="12" stroke={active ? '#00f0ff' : 'currentColor'} strokeWidth="1.8" strokeLinecap="round" />
        <line x1="19.5" y1="12" x2="21.5" y2="12" stroke={active ? '#00f0ff' : 'currentColor'} strokeWidth="1.8" strokeLinecap="round" />
      </g>
      <g className={active ? 'origin-center animate-[spin_4s_linear_infinite_reverse]' : ''}>
        <ellipse
          cx="12"
          cy="12"
          rx="5.5"
          ry="3"
          stroke={active ? '#38bdf8' : 'currentColor'}
          strokeWidth="1.3"
          strokeDasharray="4 2"
        />
        <circle cx="17.5" cy="12" r="1" fill={active ? '#ffffff' : 'currentColor'} />
      </g>
      <circle
        cx="12"
        cy="12"
        r="2.6"
        fill={active ? '#00f0ff' : 'currentColor'}
        className={active ? 'animate-[pulse_2s_ease-in-out_infinite]' : ''}
      />
      <circle cx="12" cy="12" r="1.1" fill={active ? '#ffffff' : '#07090e'} />
    </svg>
  );
};
