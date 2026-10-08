import React from 'react';
import '../../styles/skeleton.css';

interface SkeletonProps {
  className?: string;
  count?: number;
  /** line / cover / row are the design-system variants; the others are legacy. */
  type?: 'line' | 'cover' | 'row' | 'text' | 'title' | 'avatar' | 'card' | 'thumbnail';
  style?: React.CSSProperties;
}

export const Skeleton: React.FC<SkeletonProps> = ({ 
  className = '', 
  count = 1,
  type = 'text',
  style
}) => {
  const elements = Array.from({ length: count }, (_, i) => i);

  return (
    <>
      {elements.map((key) => (
        <div
          key={key}
          className={`skeleton skeleton--${type} ${className}`}
          style={style}
          aria-hidden="true"
        />
      ))}
    </>
  );
};

/**
 * Wrap skeletons in this while loading: sets aria-busy and gives screen readers a single
 * "Loading…" instead of empty shapes.
 */
export const SkeletonGroup: React.FC<{ children: React.ReactNode; label?: string; className?: string }> = ({
  children,
  label = 'Loading…',
  className,
}) => (
  <div className={className ?? 'skeleton-group'} aria-busy="true">
    <span className="visually-hidden" role="status">{label}</span>
    {children}
  </div>
);

// Predesigned skeleton layouts
export const NovelCardSkeleton: React.FC = () => (
  <div className="skeleton-card-wrapper" aria-hidden="true">
    <Skeleton className="skeleton-card-cover" />
    <div className="skeleton-card-content">
      <Skeleton type="title" className="mb-2" />
      <Skeleton type="text" count={2} />
    </div>
  </div>
);

export const NovelDetailHeroSkeleton: React.FC = () => (
  <SkeletonGroup className="skeleton-hero-wrapper">
    <div className="skeleton-hero-cover" />
    <div className="skeleton-hero-info">
      <Skeleton type="title" style={{ height: '3rem', width: '70%', marginBottom: '1rem' }} />
      <Skeleton type="text" style={{ width: '40%', marginBottom: '2rem' }} />
      <Skeleton type="text" count={3} />
      <div className="skeleton-hero-actions">
        <Skeleton style={{ width: '140px', height: '45px', borderRadius: '999px' }} />
        <Skeleton style={{ width: '160px', height: '45px', borderRadius: '999px' }} />
      </div>
    </div>
  </SkeletonGroup>
);
