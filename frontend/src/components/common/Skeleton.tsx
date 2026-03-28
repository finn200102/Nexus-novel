import React from 'react';
import '../../styles/skeleton.css';

interface SkeletonProps {
  className?: string;
  count?: number;
  type?: 'text' | 'title' | 'avatar' | 'card' | 'thumbnail';
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
        />
      ))}
    </>
  );
};

// Predesigned skeleton layouts
export const NovelCardSkeleton: React.FC = () => (
  <div className="skeleton-card-wrapper">
    <Skeleton className="skeleton-card-cover" />
    <div className="skeleton-card-content">
      <Skeleton type="title" className="mb-2" />
      <Skeleton type="text" count={2} />
    </div>
  </div>
);

export const NovelDetailHeroSkeleton: React.FC = () => (
  <div className="skeleton-hero-wrapper">
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
  </div>
);
