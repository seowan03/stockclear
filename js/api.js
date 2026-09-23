(() => {
  const localHosts = new Set(['localhost', '127.0.0.1']);
  const usesSeparateLocalFrontend = localHosts.has(window.location.hostname)
    && window.location.port
    && window.location.port !== '8000';
  const apiOrigin = usesSeparateLocalFrontend
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : '';

  const url = path => `${apiOrigin}${path.startsWith('/') ? path : `/${path}`}`;
  const request = (path, options = {}) => window.fetch(url(path), {
    ...options,
    credentials: 'include',
  });

  window.StockClearApi = Object.freeze({ url, fetch: request });
})();