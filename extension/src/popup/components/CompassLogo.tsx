import React from 'react';

/**
 * Minimalist luxury shopping concierge compass logo.
 * Monochrome charcoal (#24221F) with a delicate antique-gold (#B08D57) star / north needle accent.
 */
export const CompassLogo: React.FC<{ size?: number; className?: string }> = ({ size = 20, className = '' }) => {
  return (
    <svg 
      width={size} 
      height={size} 
      viewBox="0 0 24 24" 
      fill="none" 
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="ShopSense AI Compass Logo"
    >
      {/* Outer refined circle */}
      <circle cx="12" cy="12" r="10" stroke="#24221F" strokeWidth="1.25" strokeOpacity="0.85" />
      
      {/* Subtle cardinal guide tick marks */}
      <line x1="12" y1="2" x2="12" y2="4.5" stroke="#24221F" strokeWidth="1.2" />
      <line x1="12" y1="19.5" x2="12" y2="22" stroke="#24221F" strokeWidth="1.2" strokeOpacity="0.4" />
      <line x1="2" y1="12" x2="4.5" y2="12" stroke="#24221F" strokeWidth="1.2" strokeOpacity="0.4" />
      <line x1="19.5" y1="12" x2="22" y2="12" stroke="#24221F" strokeWidth="1.2" strokeOpacity="0.4" />
      
      {/* Directional 4-point diamond needle */}
      {/* North needle - Muted antique gold */}
      <path d="M12 4.5L14.2 12H9.8L12 4.5Z" fill="#B08D57" />
      {/* South needle - Charcoal */}
      <path d="M12 19.5L14.2 12H9.8L12 19.5Z" fill="#24221F" fillOpacity="0.7" />
      
      {/* Center pivot dot with gold rim */}
      <circle cx="12" cy="12" r="1.75" fill="#FFFDF8" stroke="#24221F" strokeWidth="1" />
      <circle cx="12" cy="12" r="0.75" fill="#B08D57" />
    </svg>
  );
};

export default CompassLogo;
