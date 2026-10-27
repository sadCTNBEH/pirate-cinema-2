import React, { useEffect, useState } from 'react';
import { Film } from 'lucide-react';

/** Existing catalog artwork, with a stable layout even when a source is missing. */
export const CinemaImage: React.FC<{
  src?: string | null;
  title: string;
  className?: string;
  priority?: boolean;
}> = ({ src, title, className = '', priority = false }) => {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return (
    <div className={`cinema-image ${className}`}>
      {src && !failed ? (
        <img src={src} alt={title} onError={() => setFailed(true)}
          loading={priority ? 'eager' : 'lazy'} fetchPriority={priority ? 'high' : 'auto'} decoding="async" />
      ) : <Film aria-label={title} className="cinema-image-fallback" />}
    </div>
  );
};

/** A backdrop is optional: portrait artwork keeps its original proportions. */
export const CinemaHero: React.FC<{
  backdrop?: string | null;
  poster?: string | null;
  title: string;
  children: React.ReactNode;
}> = ({ backdrop, poster, title, children }) => {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [backdrop]);
  const hasBackdrop = Boolean(backdrop && !failed);
  return (
    <section className={`cinema-hero ${hasBackdrop ? 'cinema-hero--backdrop' : ''}`} aria-label={title}>
      {hasBackdrop && <img className="cinema-backdrop" src={backdrop!} alt="" onError={() => setFailed(true)} decoding="async" />}
      <div className="cinema-hero-copy">{children}</div>
      <CinemaImage src={poster} title={title} className="cinema-hero-poster" priority />
    </section>
  );
};
