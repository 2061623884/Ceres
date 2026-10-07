import candidateConfig from '../.ceres-next-08/frontend/vite.config.ts';

export default async (environment) => {
  const config = await candidateConfig(environment);
  config.server = {
    ...config.server,
    host: '127.0.0.1',
    port: 18443,
    strictPort: true,
    proxy: {
      ...config.server.proxy,
      '/api': { ...config.server.proxy['/api'], target: 'http://127.0.0.1:18012' },
      '/media': { ...config.server.proxy['/media'], target: 'http://127.0.0.1:18012' },
    },
  };
  return config;
};
