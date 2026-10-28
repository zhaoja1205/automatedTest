/**
 * 用例图片（YUV 出图）展示条件判断。
 */

/**
 * 预期结果提到 yuv 且用例执行成功（PASS）时，
 * 实际结果栏才展示「查看生成的 PNG」入口。
 */
export function canShowCaseImages(
  expectedResult: string | undefined | null,
  status: string | undefined | null,
): boolean {
  if (!(expectedResult || '').toLowerCase().includes('yuv')) return false
  return (status || '').toUpperCase() === 'PASS'
}
