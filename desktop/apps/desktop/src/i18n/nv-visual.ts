/**
 * Strings for ```visual cards in chat (components/assistant-ui/embeds/visual-embed.tsx):
 * inline vector diagrams the agent draws. One block per bundled locale; each locale
 * file layers its block under `nvVisual`.
 */
import type { Translations } from './types'

export type NvVisualTranslations = Translations['nvVisual']

export const nvVisualEn: NvVisualTranslations = {
  label: 'Visual',
  drawing: 'Drawing…',
  fullscreen: 'Full screen',
  options: 'Visual options',
  viewCode: 'View code',
  viewPicture: 'View picture',
  savePng: 'Save PNG',
  saveSvg: 'Save SVG',
  copyImage: 'Copy image',
  copyCode: 'Copy code',
  failed: 'Could not draw this visual — showing the code',
  saveFailed: 'Could not save the image',
  diagram: 'Diagram',
  classicStyle: 'Original Mermaid style',
  newStyle: 'New style'
}

export const nvVisualId: NvVisualTranslations = {
  label: 'Visual',
  drawing: 'Menggambar…',
  fullscreen: 'Layar penuh',
  options: 'Opsi visual',
  viewCode: 'Lihat kode',
  viewPicture: 'Lihat gambar',
  savePng: 'Simpan PNG',
  saveSvg: 'Simpan SVG',
  copyImage: 'Salin gambar',
  copyCode: 'Salin kode',
  failed: 'Visual gagal digambar — menampilkan kode',
  saveFailed: 'Gambar gagal disimpan',
  diagram: 'Diagram',
  classicStyle: 'Gaya Mermaid asli',
  newStyle: 'Gaya baru'
}

export const nvVisualDe: NvVisualTranslations = {
  label: 'Grafik',
  drawing: 'Wird gezeichnet…',
  fullscreen: 'Vollbild',
  options: 'Grafik-Optionen',
  viewCode: 'Code anzeigen',
  viewPicture: 'Bild anzeigen',
  savePng: 'Als PNG speichern',
  saveSvg: 'Als SVG speichern',
  copyImage: 'Bild kopieren',
  copyCode: 'Code kopieren',
  failed: 'Grafik konnte nicht gezeichnet werden — Code wird angezeigt',
  saveFailed: 'Bild konnte nicht gespeichert werden',
  diagram: 'Diagramm',
  classicStyle: 'Originaler Mermaid-Stil',
  newStyle: 'Neuer Stil'
}

export const nvVisualEs: NvVisualTranslations = {
  label: 'Visual',
  drawing: 'Dibujando…',
  fullscreen: 'Pantalla completa',
  options: 'Opciones del visual',
  viewCode: 'Ver código',
  viewPicture: 'Ver imagen',
  savePng: 'Guardar PNG',
  saveSvg: 'Guardar SVG',
  copyImage: 'Copiar imagen',
  copyCode: 'Copiar código',
  failed: 'No se pudo dibujar el visual — se muestra el código',
  saveFailed: 'No se pudo guardar la imagen',
  diagram: 'Diagrama',
  classicStyle: 'Estilo Mermaid original',
  newStyle: 'Estilo nuevo'
}

export const nvVisualFr: NvVisualTranslations = {
  label: 'Visuel',
  drawing: 'Dessin en cours…',
  fullscreen: 'Plein écran',
  options: 'Options du visuel',
  viewCode: 'Voir le code',
  viewPicture: "Voir l'image",
  savePng: 'Enregistrer en PNG',
  saveSvg: 'Enregistrer en SVG',
  copyImage: "Copier l'image",
  copyCode: 'Copier le code',
  failed: 'Impossible de dessiner ce visuel — affichage du code',
  saveFailed: "Impossible d'enregistrer l'image",
  diagram: 'Diagramme',
  classicStyle: "Style Mermaid d'origine",
  newStyle: 'Nouveau style'
}

export const nvVisualJa: NvVisualTranslations = {
  label: 'ビジュアル',
  drawing: '描画中…',
  fullscreen: '全画面',
  options: 'ビジュアルのオプション',
  viewCode: 'コードを表示',
  viewPicture: '図を表示',
  savePng: 'PNG で保存',
  saveSvg: 'SVG で保存',
  copyImage: '画像をコピー',
  copyCode: 'コードをコピー',
  failed: '図を描画できませんでした — コードを表示しています',
  saveFailed: '画像を保存できませんでした',
  diagram: '図',
  classicStyle: '元の Mermaid スタイル',
  newStyle: '新しいスタイル'
}

export const nvVisualRu: NvVisualTranslations = {
  label: 'Схема',
  drawing: 'Рисую…',
  fullscreen: 'Во весь экран',
  options: 'Параметры схемы',
  viewCode: 'Показать код',
  viewPicture: 'Показать рисунок',
  savePng: 'Сохранить PNG',
  saveSvg: 'Сохранить SVG',
  copyImage: 'Копировать изображение',
  copyCode: 'Копировать код',
  failed: 'Не удалось нарисовать схему — показан код',
  saveFailed: 'Не удалось сохранить изображение',
  diagram: 'Диаграмма',
  classicStyle: 'Исходный стиль Mermaid',
  newStyle: 'Новый стиль'
}

export const nvVisualAr: NvVisualTranslations = {
  label: 'رسم توضيحي',
  drawing: 'جارٍ الرسم…',
  fullscreen: 'ملء الشاشة',
  options: 'خيارات الرسم',
  viewCode: 'عرض الشيفرة',
  viewPicture: 'عرض الصورة',
  savePng: 'حفظ PNG',
  saveSvg: 'حفظ SVG',
  copyImage: 'نسخ الصورة',
  copyCode: 'نسخ الشيفرة',
  failed: 'تعذّر رسم هذا الشكل — يتم عرض الشيفرة',
  saveFailed: 'تعذّر حفظ الصورة',
  diagram: 'مخطط',
  classicStyle: 'نمط Mermaid الأصلي',
  newStyle: 'النمط الجديد'
}

export const nvVisualZh: NvVisualTranslations = {
  label: '图示',
  drawing: '正在绘制…',
  fullscreen: '全屏',
  options: '图示选项',
  viewCode: '查看代码',
  viewPicture: '查看图片',
  savePng: '保存为 PNG',
  saveSvg: '保存为 SVG',
  copyImage: '复制图片',
  copyCode: '复制代码',
  failed: '无法绘制此图示，已显示代码',
  saveFailed: '无法保存图片',
  diagram: '图表',
  classicStyle: '原始 Mermaid 样式',
  newStyle: '新样式'
}

export const nvVisualZhHant: NvVisualTranslations = {
  label: '圖示',
  drawing: '正在繪製…',
  fullscreen: '全螢幕',
  options: '圖示選項',
  viewCode: '檢視程式碼',
  viewPicture: '檢視圖片',
  savePng: '儲存為 PNG',
  saveSvg: '儲存為 SVG',
  copyImage: '複製圖片',
  copyCode: '複製程式碼',
  failed: '無法繪製此圖示，已顯示程式碼',
  saveFailed: '無法儲存圖片',
  diagram: '圖表',
  classicStyle: '原始 Mermaid 樣式',
  newStyle: '新樣式'
}
