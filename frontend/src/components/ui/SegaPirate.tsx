/**
 * @file components/ui/SegaPirate.tsx
 * @description Векторный 16-битный пиксель-арт пирата в стилистике SEGA Genesis / Mega Drive.
 */

import React from 'react';

interface SegaPirateProps {
  size?: number;
  className?: string;
}

export const SegaPirate: React.FC<SegaPirateProps> = ({
  size = 44,
  className = '',
}) => {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      shapeRendering="crispEdges"
      className={`inline-block select-none ${className}`}
    >
      {/* ТЕМНЫЙ ФОН ПОРТРЕТА SEGA */}
      <rect width="32" height="32" rx="4" fill="#080c16" />

      {/* ШЛЯПА ПИРАТА */}
      <rect x="10" y="3" width="12" height="4" fill="#131c2e" />
      <rect x="8" y="5" width="16" height="2" fill="#1a273e" />
      <rect x="11" y="2" width="10" height="2" fill="#0b101a" />

      {/* ЧЕРЕП НА ШЛЯПЕ */}
      <rect x="14" y="4" width="4" height="2" fill="#00f0ff" />
      <rect x="15" y="6" width="2" height="1" fill="#00f0ff" />
      <rect x="15" y="4" width="1" height="1" fill="#080c16" />
      <rect x="16" y="4" width="1" height="1" fill="#080c16" />

      {/* ПОЛЯ ШЛЯПЫ */}
      <rect x="4" y="7" width="24" height="3" fill="#131c2e" />
      <rect x="2" y="8" width="28" height="2" fill="#1a273e" />
      <rect x="2" y="7" width="2" height="2" fill="#0b101a" />
      <rect x="28" y="7" width="2" height="2" fill="#0b101a" />
      <rect x="5" y="9" width="22" height="1" fill="#00f0ff" opacity="0.8" />

      {/* ЛИЦО И КОЖА */}
      <rect x="8" y="10" width="16" height="11" fill="#d97736" />
      <rect x="9" y="10" width="14" height="10" fill="#f09953" />
      <rect x="10" y="10" width="5" height="1" fill="#ffb87a" />
      <rect x="17" y="10" width="5" height="1" fill="#ffb87a" />

      {/* ПОВЯЗКА НА ЛЕВОМ ГЛАЗУ */}
      <rect x="8" y="12" width="16" height="1" fill="#0b101a" />
      <rect x="9" y="11" width="3" height="1" fill="#0b101a" />
      <rect x="20" y="13" width="3" height="1" fill="#0b101a" />
      <rect x="9" y="12" width="6" height="5" fill="#0b101a" />
      <rect x="10" y="11" width="4" height="1" fill="#00f0ff" opacity="0.6" />
      <rect x="11" y="13" width="3" height="3" fill="#00f0ff" />
      <rect x="12" y="14" width="1" height="1" fill="#ffffff" />
      <rect x="10" y="14" width="1" height="1" fill="#38bdf8" />
      <rect x="14" y="14" width="1" height="1" fill="#38bdf8" />

      {/* ПРАВЫЙ ГЛАЗ И ШРАМ */}
      <rect x="17" y="12" width="6" height="1" fill="#3a1c0d" />
      <rect x="18" y="13" width="4" height="2" fill="#ffffff" />
      <rect x="19" y="13" width="2" height="2" fill="#1e293b" />
      <rect x="18" y="14" width="1" height="1" fill="#713f12" />
      <rect x="20" y="16" width="1" height="2" fill="#00f0ff" opacity="0.75" />

      {/* НОС И УХМЫЛКА С ЗОЛОТЫМ ЗУБОМ */}
      <rect x="15" y="14" width="2" height="4" fill="#c25e24" />
      <rect x="14" y="17" width="4" height="1" fill="#a04616" />
      <rect x="13" y="19" width="6" height="1" fill="#0b101a" />
      <rect x="14" y="19" width="1" height="1" fill="#facc15" />

      {/* БОРОДА */}
      <rect x="7" y="18" width="4" height="7" fill="#1b120c" />
      <rect x="21" y="18" width="4" height="7" fill="#1b120c" />
      <rect x="9" y="21" width="14" height="5" fill="#1b120c" />
      <rect x="11" y="26" width="10" height="2" fill="#1b120c" />
      <rect x="13" y="28" width="6" height="1" fill="#1b120c" />
      <rect x="8" y="20" width="2" height="4" fill="#332217" />
      <rect x="22" y="20" width="2" height="4" fill="#332217" />
      <rect x="12" y="23" width="8" height="2" fill="#332217" />

      {/* ВОРОТНИК */}
      <rect x="5" y="29" width="22" height="3" fill="#0f172a" />
      <rect x="12" y="29" width="8" height="1" fill="#00f0ff" opacity="0.6" />
    </svg>
  );
};
