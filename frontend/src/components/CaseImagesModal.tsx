/**
 * 用例图片弹窗：展示从板端下载到本机的 YUV 出图 PNG。
 *
 * 图片通过 axios（带 X-Session-ID）以 blob 方式读取，
 * 避免 <img src> 无法携带自定义请求头导致 session 校验失败。
 */
import { useEffect, useState } from 'react'
import { Empty, Image, Modal, Space, Spin, Typography, message } from 'antd'
import { isAxiosError } from 'axios'
import { getCaseImageBlob, getCaseImages } from '../api/axios'

const { Text } = Typography

interface Props {
  caseId: string | null
  open: boolean
  onClose: () => void
}

interface LoadedImage {
  name: string
  url: string
}

export default function CaseImagesModal({ caseId, open, onClose }: Props) {
  const [loading, setLoading] = useState(false)
  const [images, setImages] = useState<LoadedImage[]>([])
  const [note, setNote] = useState('')

  useEffect(() => {
    if (!open || !caseId) return
    let cancelled = false
    const objectUrls: string[] = []

    setLoading(true)
    setImages([])
    setNote('')

    void (async () => {
      try {
        const res = await getCaseImages(caseId)
        const list = res.data.images || []
        if (list.length === 0) {
          if (!cancelled) setNote(res.data.message || '未找到生成的 PNG 图片')
          return
        }
        const loaded = await Promise.all(
          list.map(async (item) => {
            const blobRes = await getCaseImageBlob(caseId, item.name)
            const url = URL.createObjectURL(blobRes.data)
            objectUrls.push(url)
            return { name: item.name, url }
          }),
        )
        if (!cancelled) setImages(loaded)
      } catch (error) {
        if (cancelled) return
        const detail = isAxiosError<{ detail?: string }>(error)
          ? error.response?.data?.detail || error.message
          : (error as Error)?.message
        setNote(detail || '读取图片失败')
        message.error(detail || '读取图片失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => {
      cancelled = true
      objectUrls.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [open, caseId])

  return (
    <Modal
      open={open}
      width={920}
      footer={null}
      destroyOnClose
      onCancel={onClose}
      title={caseId ? `YUV 出图 - ${caseId}` : 'YUV 出图'}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: '48px 0' }}>
          <Spin />
          <div style={{ marginTop: 12, color: '#666' }}>正在加载图片…</div>
        </div>
      ) : images.length === 0 ? (
        <Empty description={note || '未找到生成的 PNG 图片'} style={{ padding: '32px 0' }} />
      ) : (
        <Image.PreviewGroup>
          <Space wrap size={16} align="start">
            {images.map((item) => (
              <div key={item.name} style={{ textAlign: 'center' }}>
                <Image
                  src={item.url}
                  width={260}
                  style={{ border: '1px solid #eee', borderRadius: 6 }}
                  alt={item.name}
                />
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }} copyable>
                    {item.name}
                  </Text>
                </div>
              </div>
            ))}
          </Space>
        </Image.PreviewGroup>
      )}
    </Modal>
  )
}
