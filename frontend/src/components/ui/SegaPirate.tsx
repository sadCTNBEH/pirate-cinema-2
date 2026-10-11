/**
 * @file components/ui/SegaPirate.tsx
 * @description Официальный логотип Pirate Cinema.
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
    <img
      src="/logo.png"
      alt="Pirate Cinema"
      width={size}
      height={size}
      className={`inline-block select-none object-cover ${className}`}
    />
  );
};
