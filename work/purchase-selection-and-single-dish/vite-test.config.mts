import base from '../../frontend/vite.config.ts'

export default async (env) => {
  const config = await base(env)
  return {
    ...config,
    server: {
      ...config.server,
      port: 8444,
      proxy: {
        '/api': { target: 'http://127.0.0.1:8013' },
        '/media': { target: 'http://127.0.0.1:8013' },
      },
    },
  }
}
