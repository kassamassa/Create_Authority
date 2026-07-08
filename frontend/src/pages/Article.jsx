import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const CATEGORY_COLORS = {
  '属人化解消': 'bg-blue-100 text-blue-800',
  '引き継ぎ・マニュアル化': 'bg-green-100 text-green-800',
  '採用・育成コスト削減': 'bg-purple-100 text-purple-800',
  '業務時間削減': 'bg-orange-100 text-orange-800',
  'ゼロコストDX': 'bg-teal-100 text-teal-800',
}

const DIFFICULTY_STYLES = {
  '易': 'bg-green-50 text-green-700 border border-green-200',
  '中': 'bg-yellow-50 text-yellow-700 border border-yellow-200',
  '難': 'bg-red-50 text-red-700 border border-red-200',
}

// ローカル確認用ダミー詳細データ
const DEMO_ARTICLE = {
  id: 'demo-1',
  title: '製造業A社：AIチャットボットで問い合わせ対応を80%自動化',
  summary:
    '月300件超の社内問い合わせをAIが自動回答。担当者の対応工数を週20時間削減し、属人化していたナレッジを組織知に転換した事例。',
  category: '属人化解消',
  difficulty: '中',
  source_url: 'https://example.com/dx-case-manufacturing',
  metadata: {
    faq: [
      {
        q: 'どのようなAIツールを使いましたか？',
        a: 'ChatGPTのAPIをベースにしたカスタムチャットボットを社内システムに組み込みました。導入コストは月5万円以下で抑えられています。',
      },
      {
        q: '社員の受け入れはスムーズでしたか？',
        a: '最初は「AIに仕事を奪われる」という懸念もありましたが、単純な問い合わせ対応から解放されることへの歓迎の声が大きく、3か月で定着しました。',
      },
      {
        q: '導入前後でどのような変化がありましたか？',
        a: '担当者の残業時間が月平均15時間削減され、顧客対応などより付加価値の高い業務に時間を使えるようになりました。',
      },
    ],
  },
}

function FaqItem({ item, index, isOpen, onToggle }) {
  return (
    <div className="border border-gray-100 rounded-xl overflow-hidden">
      <button
        onClick={() => onToggle(index)}
        className="w-full text-left px-5 py-4 flex items-start justify-between gap-4 hover:bg-gray-50 transition-colors"
      >
        <span className="font-medium text-gray-800 text-sm leading-relaxed">
          Q. {item.q}
        </span>
        <span
          className={`text-gray-400 flex-shrink-0 mt-0.5 transition-transform duration-200 ${
            isOpen ? 'rotate-180' : ''
          }`}
        >
          ▾
        </span>
      </button>
      {isOpen && (
        <div className="px-5 py-4 bg-indigo-50 border-t border-indigo-100">
          <p className="text-gray-700 text-sm leading-relaxed">A. {item.a}</p>
        </div>
      )}
    </div>
  )
}

export default function Article() {
  const { id } = useParams()
  const [article, setArticle] = useState(null)
  const [loading, setLoading] = useState(true)
  const [usedDemo, setUsedDemo] = useState(false)
  const [openFaq, setOpenFaq] = useState(null)

  useEffect(() => {
    // JSON-LDのクリーンアップ
    return () => {
      document.getElementById('article-jsonld')?.remove()
    }
  }, [id])

  useEffect(() => {
    setLoading(true)
    setOpenFaq(null)

    fetch(`${API_BASE}/articles/${id}`)
      .then(res => {
        if (!res.ok) throw new Error()
        return res.json()
      })
      .then(data => {
        setArticle(data)
        injectJsonLd(data)
      })
      .catch(() => {
        setArticle(DEMO_ARTICLE)
        setUsedDemo(true)
        injectJsonLd(DEMO_ARTICLE)
      })
      .finally(() => setLoading(false))
  }, [id])

  function injectJsonLd(data) {
    document.getElementById('article-jsonld')?.remove()
    const faq = data.metadata?.faq || []
    if (!faq.length) return
    const script = document.createElement('script')
    script.type = 'application/ld+json'
    script.id = 'article-jsonld'
    script.textContent = JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'Article',
      headline: data.title,
      description: data.summary || '',
      articleSection: data.category,
      mainEntity: faq.map(item => ({
        '@type': 'Question',
        name: item.q,
        acceptedAnswer: { '@type': 'Answer', text: item.a },
      })),
    })
    document.head.appendChild(script)
  }

  const toggleFaq = i => setOpenFaq(prev => (prev === i ? null : i))

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-10 w-10 border-4 border-indigo-600 border-t-transparent" />
      </div>
    )
  }

  if (!article) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center gap-4 px-4 text-center">
        <p className="text-gray-500 text-lg">記事が見つかりませんでした。</p>
        <Link to="/" className="text-indigo-600 hover:underline text-sm">
          ← 一覧に戻る
        </Link>
      </div>
    )
  }

  const faq = article.metadata?.faq || []
  const catColor = CATEGORY_COLORS[article.category] || 'bg-gray-100 text-gray-700'
  const diffStyle =
    DIFFICULTY_STYLES[article.difficulty] || 'bg-gray-50 text-gray-600 border border-gray-200'

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 py-4 flex items-center gap-3">
          <Link to="/" className="text-xl font-bold text-indigo-700">
            Create Authority
          </Link>
          <span className="hidden sm:block text-xs text-gray-400 border-l border-gray-200 pl-3">
            DX事例データベース
          </span>
        </div>
      </header>

      <main className="flex-1 max-w-4xl mx-auto w-full px-4 sm:px-6 py-10">
        {usedDemo && (
          <div className="mb-6 bg-amber-50 border border-amber-200 text-amber-700 text-sm px-4 py-3 rounded-lg">
            ⚠️ APIに接続できないため、サンプルデータを表示しています。
          </div>
        )}

        {/* Back link */}
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-indigo-600 mb-8 transition-colors"
        >
          ← 一覧に戻る
        </Link>

        {/* Article header card */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-8 mb-6">
          <div className="flex flex-wrap items-center gap-2 mb-5">
            <span className={`text-xs font-medium px-2.5 py-0.5 rounded-full ${catColor}`}>
              {article.category || '未分類'}
            </span>
            <span className={`text-xs px-2 py-0.5 rounded ${diffStyle}`}>
              難易度：{article.difficulty || '中'}
            </span>
          </div>

          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 mb-6 leading-snug">
            {article.title}
          </h1>

          {article.summary && (
            <div className="bg-indigo-50 rounded-xl p-5 border-l-4 border-indigo-500">
              <p className="text-xs font-semibold text-indigo-600 mb-2 uppercase tracking-wider">
                AI要約
              </p>
              <p className="text-gray-700 text-sm leading-relaxed">{article.summary}</p>
            </div>
          )}
        </div>

        {/* FAQ section */}
        {faq.length > 0 && (
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-8 mb-6">
            <h2 className="text-xl font-bold text-gray-900 mb-6 flex items-center gap-2">
              <span className="w-6 h-6 bg-indigo-100 text-indigo-700 rounded-full text-xs flex items-center justify-center font-bold">
                Q
              </span>
              よくある質問 Q&amp;A
            </h2>
            <div className="space-y-3">
              {faq.map((item, i) => (
                <FaqItem
                  key={i}
                  item={item}
                  index={i}
                  isOpen={openFaq === i}
                  onToggle={toggleFaq}
                />
              ))}
            </div>
          </div>
        )}

        {/* Source link */}
        {article.source_url && (
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 mb-6">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
              元記事
            </p>
            <a
              href={article.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-600 hover:underline text-sm break-all"
            >
              {article.source_url}
            </a>
          </div>
        )}

        {/* CTA */}
        <div className="bg-indigo-600 rounded-2xl p-8 text-center text-white">
          <p className="font-bold text-lg mb-1">この記事が役立ちましたか？</p>
          <p className="text-indigo-200 text-sm mb-5">
            週次でDX事例をお届けするメルマガに登録して、最新情報を見逃さず受け取りましょう。
          </p>
          <Link
            to="/"
            className="inline-block bg-white text-indigo-700 font-semibold px-6 py-2.5 rounded-lg text-sm hover:bg-indigo-50 transition-colors"
          >
            メルマガ登録はこちら →
          </Link>
        </div>
      </main>

      {/* Footer */}
      <footer className="bg-gray-900 text-gray-500 py-8 px-4 text-center text-xs mt-10">
        <p>© 2025 Create Authority. All rights reserved.</p>
      </footer>
    </div>
  )
}
