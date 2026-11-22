import { buildConfig } from './monitor-dialog';

const base = { method: 'GET', expectedStatus: '', keyword: '', recordType: 'A' };

describe('buildConfig', () => {
  it('builds http config from the form fields', () => {
    expect(buildConfig('http', base)).toEqual({ method: 'GET' });
    expect(
      buildConfig('http', { ...base, method: 'HEAD', expectedStatus: '200, 204', keyword: ' ok ' }),
    ).toEqual({ method: 'HEAD', expected_status: [200, 204], keyword: 'ok' });
  });

  it('builds dns and tcp config', () => {
    expect(buildConfig('dns', { ...base, recordType: 'AAAA' })).toEqual({ record_type: 'AAAA' });
    expect(buildConfig('tcp', base)).toEqual({});
  });
});
