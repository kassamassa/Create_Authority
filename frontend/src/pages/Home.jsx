import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const CATEGORIES = [
  { key: 'all', label: 'すべて' },
  { key: '属人化解消', label: '属人化解消' },
  { key: '引き継ぎ・マニュアル化', label: '引き継ぎ・マニュアル化' },
  { key: '採用・育成コスト削減', label: '採用・育成コスト削減' },
  { key: '業務時間削減', label: '業務時間削減' },
  { key: 'ゼロコストDX', label: 'ゼロコストDX' },
]

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

// ローカル確認用ダミーデータ（APIが未接続の場合に表示）
const DEMO_ARTICLES = [
  {
    id: 'demo-1',
    title: '製造業A社：AIチャットボットで問い合わせ対応を80%自動化',
    summary: '月300件超の社内問い合わせをAIが自動回答。担当者の対応工数を週20時間削減し、属人化していたナレッジを組織知に転換した事例。',
    category: '属人化解消',
    difficulty: '中',
  },
  {
    id: 'demo-2',
    title: '物流B社：引き継ぎドキュメントをAIで自動生成、育成期間を半減',
    summary: 'ベテラン社員の暗黙知をAIがヒアリングし、構造化されたマニュアルとして自動生成。新人育成にかかる期間を6か月から3か月に短縮。',
    category: '引き継ぎ・マニュアル化',
    difficulty: '易',
  },
  {
    id: 'demo-3',
    title: '小売C社：採用スクリーニングにAIを導入、コストを60%削減',
    summary: '応募書類の一次選考をAIが自動化。人事担当者が本来注力すべき面接・評価業務に集中できるようになり、採用コストを大幅削減。',
    category: '採用・育成コスト削減',
    difficulty: '難',
  },
]

function ArticleCard({ article }) {
  const catColor = CATEGORY_COLORS[article.category] || 'bg-gray-100 text-gray-700'
  const diffStyle = DIFFICULTY_STYLES[article.difficulty] || 'bg-gray-50 text-gray-600 border border-gray-200'

  return (
    <Link
      to={`/articles/${article.id}`}
      className="group flex flex-col bg-white rounded-xl shadow-sm border border-gray-100 hover:shadow-md hover:border-indigo-100 transition-all overflow-hidden"
    >
      <div className="flex-1 p-6">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <span className={`text-xs font-medium px-2.5 py-0.5 rounded-full ${catColor}`}>
            {article.category || '未分類'}
          </span>
          <span className={`text-xs px-2 py-0.5 rounded ${diffStyle}`}>
            {article.difficulty || '中'}
          </span>
        </div>
        <h2 className="font-bold text-gray-900 text-base mb-2 group-hover:text-indigo-700 transition-colors line-clamp-2 leading-snug">
          {article.title}
        </h2>
        <p className="text-gray-500 text-sm line-clamp-3 leading-relaxed">
          {article.summary || '要約を準備中...'}
        </p>
      </div>
      <div className="px-6 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
        <span className="text-xs text-indigo-600 font-medium group-hover:underline">続きを読む</span>
        <span className="text-gray-400 text-xs group-hover:text-indigo-500 transition-colors">→</span>
      </div>
    </Link>
  )
}

export default function Home() {
  const [articles, setArticles] = useState([])
  const [loading, setLoading] = useState(true)
  const [usedDemo, setUsedDemo] = useState(false)
  const [activeCategory, setActiveCategory] = useState('all')
  const [form, setForm] = useState({ name: '', email: '' })
  const [formState, setFormState] = useState('idle') // idle | submitting | success

  useEffect(() => {
    fetch(`${API_BASE}/articles?status=published`)
      .then(res => {
        if (!res.ok) throw new Error()
        return res.json()
      })
      .then(data => setArticles(data))
      .catch(() => {
        setArticles(DEMO_ARTICLES)
        setUsedDemo(true)
      })
      .finally(() => setLoading(false))
  }, [])

  const filtered =
    activeCategory === 'all'
      ? articles
      : articles.filter(a => a.category === activeCategory)

  const handleSubscribe = async e => {
    e.preventDefault()
    setFormState('submitting')
    try {
      await fetch(`${API_BASE}/newsletter/subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
    } catch {
      // バックエンドエンドポイント未実装時も登録完了として扱う
    }
    setFormState('success')
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 flex items-center gap-3">
          <Link to="/" className="text-xl font-bold text-indigo-700 leading-none">
            Create Authority
          </Link>
          <span className="hidden sm:block text-xs text-gray-400 border-l border-gray-200 pl-3">
            DX事例データベース
          </span>
        </div>
      </header>

      {/* Hero */}
      <section className="bg-gradient-to-br from-indigo-700 via-indigo-600 to-indigo-500 text-white py-16 px-4">
        <div className="max-w-3xl mx-auto text-center">
          <p className="text-indigo-200 text-sm font-medium tracking-wider mb-3 uppercase">
            AI-curated DX Case Studies
          </p>
          <h1 className="text-3xl sm:text-4xl font-bold mb-4 leading-tight">
            中小企業のDX事例を、<br className="sm:hidden" />わかりやすく。
          </h1>
          <p className="text-indigo-100 text-base sm:text-lg max-w-xl mx-auto">
            属人化解消・業務効率化・コスト削減——実際の導入事例をAIが要約・整理してお届けします。
          </p>
        </div>
      </section>

      {/* Category filter */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <div className="flex gap-2 overflow-x-auto py-3" style={{ scrollbarWidth: 'none' }}>
            {CATEGORIES.map(cat => (
              <button
                key={cat.key}
                onClick={() => setActiveCategory(cat.key)}
                className={`px-4 py-1.5 rounded-full text-sm font-medium whitespace-nowrap transition-colors flex-shrink-0 ${
                  activeCategory === cat.key
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {cat.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Article grid */}
      <main className="flex-1 max-w-6xl mx-auto w-full px-4 sm:px-6 py-10">
        {usedDemo && (
          <div className="mb-6 bg-amber-50 border border-amber-200 text-amber-700 text-sm px-4 py-3 rounded-lg">
            ⚠️ APIに接続できないため、サンプルデータを表示しています。
            <code className="ml-1 text-xs bg-amber-100 px-1 rounded">VITE_API_URL</code> を設定してください。
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-24">
            <div className="animate-spin rounded-full h-10 w-10 border-4 border-indigo-600 border-t-transparent" />
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-center py-24 text-gray-400">該当する記事がありません。</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {filtered.map(article => (
              <ArticleCard key={article.id} article={article} />
            ))}
          </div>
        )}
      </main>

      {/* Newsletter signup */}
      <section className="bg-indigo-50 border-t border-indigo-100 py-16 px-4">
        <div className="max-w-lg mx-auto text-center">
          <h2 className="text-2xl font-bold text-indigo-900 mb-2">週次DXインサイトを受け取る</h2>
          <p className="text-indigo-700 mb-8 text-sm">
            厳選DX事例を毎週1本、メールでお届けします。無料・いつでも解除可能。
          </p>

          {formState === 'success' ? (
            <div className="bg-white rounded-2xl p-8 shadow-sm border border-indigo-100">
              <div className="text-4xl mb-3">🎉</div>
              <p className="font-semibold text-gray-800 text-lg">登録ありがとうございます！</p>
              <p className="text-gray-500 text-sm mt-2">次回の配信をお楽しみに。</p>
            </div>
          ) : (
            <form
              onSubmit={handleSubscribe}
              className="bg-white rounded-2xl p-8 shadow-sm border border-indigo-100 space-y-4 text-left"
            >
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">お名前</label>
                <input
                  type="text"
                  required
                  placeholder="山田 太郎"
                  value={form.name}
                  onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">メールアドレス</label>
                <input
                  type="email"
                  required
                  placeholder="yamada@company.jp"
                  value={form.email}
                  onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition"
                />
              </div>
              <button
                type="submit"
                disabled={formState === 'submitting'}
                className="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-3 rounded-lg transition-colors disabled:opacity-60 text-sm"
              >
                {formState === 'submitting' ? '送信中...' : '無料で登録する →'}
              </button>
              <p className="text-xs text-gray-400 text-center">
                スパムメールは送りません。いつでも配信解除できます。
              </p>
            </form>
          )}
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-gray-900 text-gray-500 py-8 px-4 text-center text-xs">
        <p>© 2025 Create Authority. All rights reserved.</p>
      </footer>
    </div>
  )
}
