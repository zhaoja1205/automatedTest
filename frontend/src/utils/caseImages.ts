/**
 * 用例图片（YUV 出图）展示条件判断。
 */

/** 预期结果提到 yuv 的用例才可能产生 YUV 出图 PNG。 */
export function isYuvCase(expectedResult: string | undefined | null): boolean {
  return (expectedResult || '').toLowerCase().includes('yuv')
}

/**
 * 只要该用例目录下已生成 PNG，就展示「查看生成的 PNG」入口，
 * 与用例执行状态（PASS / FAIL / …）无关。
 */
export function canShowCaseImages(
  expectedResult: string | undefined | null,
  hasImages: boolean | undefined | null,
): boolean {
  return isYuvCase(expectedResult) && !!hasImages
}
