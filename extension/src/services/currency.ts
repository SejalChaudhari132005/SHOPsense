const EXCHANGE_RATES_TO_INR: Record<string, number> = {
  INR: 1,
  USD: 83.3333333333,
  EUR: 90,
  GBP: 106.6666666667,
  CAD: 61.6666666667,
  AUD: 55,
  JPY: 0.5583333333,
};

export function formatPriceInINR(amount: number | null, currency: string | null): string {
  if (amount === null || !Number.isFinite(amount) || !currency) {
    return 'Price unavailable';
  }

  const rateToInr = EXCHANGE_RATES_TO_INR[currency.trim().toUpperCase()];
  if (rateToInr === undefined) {
    return 'Price unavailable';
  }

  const inrAmount = amount * rateToInr;
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(inrAmount);
}
