import { buildCompleteLogsPath } from './FailedTestcaseAnalysis';

jest.mock('../api', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));

describe('buildCompleteLogsPath', () => {
  test('appends testcase name with dots replaced by slashes', () => {
    const logPath = 'http://10.40.234.216/logs/6a886960d24d8266de3d0c99/6a886960d24d8266de3d0cbd/';
    const testcaseName =
      'cdp.curator.goldsuite_iointegrity.test_goldsuite.CuratorGoldSuiteTest.test_gold___disk_offline_and_node_removal';
    expect(buildCompleteLogsPath(logPath, testcaseName)).toBe(
      'http://10.40.234.216/logs/6a886960d24d8266de3d0c99/6a886960d24d8266de3d0cbd/cdp/curator/goldsuite_iointegrity/test_goldsuite/CuratorGoldSuiteTest/test_gold___disk_offline_and_node_removal/'
    );
  });

  test('normalizes missing trailing slash on the log path', () => {
    expect(
      buildCompleteLogsPath(
        'http://10.40.234.216/logs/abc/def',
        'pkg.mod.Test.test_foo'
      )
    ).toBe('http://10.40.234.216/logs/abc/def/pkg/mod/Test/test_foo/');
  });

  test('returns empty string when log path or testcase name is missing', () => {
    expect(buildCompleteLogsPath('', 'pkg.mod.test')).toBe('');
    expect(buildCompleteLogsPath('http://host/logs/', '')).toBe('');
  });
});
