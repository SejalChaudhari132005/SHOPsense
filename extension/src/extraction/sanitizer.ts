// ShopSense AI — Untrusted Content Sanitizer & Prompt Injection Defense Engine
// Rule: Treat all webpage text, titles, specifications, and descriptions as UNTRUSTED input.

/**
 * Patterns associated with prompt injection, jailbreaking, or system prompt override attempts.
 */
const INJECTION_PATTERNS: RegExp[] = [
  /ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules|commands)/gi,
  /disregard\s+(all\s+)?(previous|prior|above|system)\s+(instructions|prompts|rules)/gi,
  /system\s*:\s*/gi,
  /\[system\]/gi,
  /\[developer\s*mode\]/gi,
  /assistant\s*:\s*/gi,
  /you\s+are\s+now\s+(in\s+developer\s+mode|dan|an\s+unrestricted)/gi,
  /override\s+(all\s+)?(system\s+|safety\s+|security\s+)?(rules|guidelines|parameters|instructions)/gi,
  /new\s+system\s+instruction\s*:/gi,
  /<\|im_start\|>/gi,
  /<\|im_end\|>/gi,
  /```(system|instructions?)/gi,
  /bypass\s+all\s+(filters|safeguards)/gi,
];

/**
 * Strips HTML markup, tags, scripts, and invisible zero-width unicode characters.
 */
export function stripHtmlAndControlChars(input: string): string {
  if (!input) return '';
  return input
    // Remove script and style tags with content
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, ' ')
    .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, ' ')
    // Remove HTML tags
    .replace(/<[^>]+>/g, ' ')
    // Remove invisible control characters & zero-width spaces
    .replace(/[\u200B-\u200D\uFEFF\u0000-\u0008\u000E-\u001F]/g, '')
    // Normalize whitespace
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Sanitizes untrusted text extracted from shopping pages.
 * Neutralizes prompt injections, strips markup, and caps maximum length.
 */
export function sanitizeUntrustedText(text: string | null | undefined, maxLength = 300): string {
  if (!text) return '';

  let cleaned = stripHtmlAndControlChars(text);

  // Neutralize prompt injection attempts
  for (const pattern of INJECTION_PATTERNS) {
    if (pattern.test(cleaned)) {
      cleaned = cleaned.replace(pattern, '[Filtered Instruction]');
    }
  }

  // Cap maximum length to protect LLM context windows from token flooding
  if (cleaned.length > maxLength) {
    cleaned = cleaned.substring(0, maxLength).trim() + '...';
  }

  return cleaned;
}

/**
 * Validates and sanitizes a product URL.
 * Strips affiliate and tracking query parameters while ensuring strict HTTP/HTTPS protocol.
 */
export function sanitizeUrl(rawUrl: string | null | undefined, expectedHostDomain?: string): string | null {
  if (!rawUrl || typeof rawUrl !== 'string') return null;

  const trimmed = rawUrl.trim();
  // Reject javascript:, data:, file:, etc.
  if (!/^https?:\/\//i.test(trimmed)) {
    return null;
  }

  try {
    const parsed = new URL(trimmed);

    // Verify protocol is strictly http or https
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return null;
    }

    // Verify host if expectedHostDomain is specified
    if (expectedHostDomain) {
      const hostname = parsed.hostname.toLowerCase();
      const expected = expectedHostDomain.toLowerCase().replace(/^\./, '');
      if (hostname !== expected && !hostname.endsWith('.' + expected)) {
        return null;
      }
    }

    // Strip common tracking and session parameters
    const trackingKeys = [
      'utm_source',
      'utm_medium',
      'utm_campaign',
      'utm_term',
      'utm_content',
      'ref',
      'ref_',
      'tag',
      'ascsubtag',
      'pf_rd_r',
      'pf_rd_p',
      'pf_rd_m',
      'pf_rd_s',
      'pf_rd_t',
      'pf_rd_i',
      'qid',
      'sr',
      'keywords',
      'sprefix',
      'crid',
      'cv_ct_id',
      'session-id',
      'session-id-time',
    ];

    trackingKeys.forEach((key) => parsed.searchParams.delete(key));

    return parsed.toString();
  } catch {
    return null;
  }
}

/**
 * Validates and sanitizes an image URL.
 */
export function sanitizeImageUrl(rawUrl: string | null | undefined): string | null {
  if (!rawUrl || typeof rawUrl !== 'string') return null;

  const trimmed = rawUrl.trim();
  // Image must be HTTP or HTTPS
  if (!/^https?:\/\//i.test(trimmed)) {
    return null;
  }

  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return null;
    }
    // Reject data or blob URIs
    return parsed.toString();
  } catch {
    return null;
  }
}

/**
 * Sanitizes a specifications dictionary, ensuring safe keys and values.
 */
export function sanitizeSpecifications(
  specs: Record<string, any> | null | undefined
): Record<string, string | number | boolean> {
  if (!specs || typeof specs !== 'object') return {};

  const cleanSpecs: Record<string, string | number | boolean> = {};

  for (const [rawKey, rawVal] of Object.entries(specs)) {
    const cleanKey = sanitizeUntrustedText(rawKey, 50);
    if (!cleanKey) continue;

    if (typeof rawVal === 'number' && Number.isFinite(rawVal)) {
      cleanSpecs[cleanKey] = rawVal;
    } else if (typeof rawVal === 'boolean') {
      cleanSpecs[cleanKey] = rawVal;
    } else if (typeof rawVal === 'string') {
      const cleanVal = sanitizeUntrustedText(rawVal, 150);
      if (cleanVal) {
        cleanSpecs[cleanKey] = cleanVal;
      }
    }
  }

  return cleanSpecs;
}
