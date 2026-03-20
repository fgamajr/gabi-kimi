import React from 'react';
import { useNavigate } from 'react-router-dom';
import { SectionBadge } from '@/components/Badges';
import { Icons } from '@/components/Icons';
import type { EditorialHighlight, EditorialHighlightsResponse } from '@/lib/api';

interface Props {
  data: EditorialHighlightsResponse;
}

const CATEGORY_STYLES: Record<string, { icon: React.ReactNode; badgeClass: string; labelColor: string }> = {
  concursos: {
    icon: <Icons.building className="w-5 h-5" />,
    badgeClass: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    labelColor: 'text-emerald-600 dark:text-emerald-400',
  },
  economia: {
    icon: <Icons.trending className="w-5 h-5" />,
    badgeClass: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400',
    labelColor: 'text-rose-600 dark:text-rose-400',
  },
  politica: {
    icon: <Icons.document className="w-5 h-5" />,
    badgeClass: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    labelColor: 'text-blue-600 dark:text-blue-400',
  },
  tcu_destaque: {
    icon: <Icons.scale className="w-5 h-5" />,
    badgeClass: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    labelColor: 'text-amber-600 dark:text-amber-400',
  },
};

const ART_TYPE_ICONS: Record<string, React.FC<{ className?: string }>> = {
  'decreto': Icons.document,
  'medida provisória': Icons.document,
  'medida-provisoria': Icons.document,
  'lei': Icons.book,
  'edital': Icons.bookmark,
  'resolução': Icons.scale,
  'resolucao': Icons.scale,
};

function getDecoIcon(artType: string): React.FC<{ className?: string }> {
  const key = artType.toLowerCase().trim();
  for (const [k, icon] of Object.entries(ART_TYPE_ICONS)) {
    if (key.includes(k)) return icon;
  }
  return Icons.document;
}

const formatDayMonth = (d: string) => {
  try {
    return new Date(d).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
  } catch {
    return d;
  }
};

const FeaturedCard: React.FC<{ highlight: EditorialHighlight }> = ({ highlight }) => {
  const navigate = useNavigate();
  const DecoIcon = getDecoIcon(highlight.art_type);

  return (
    <div
      className="group relative bg-card border border-border rounded-2xl overflow-hidden hover:shadow-lg transition-all duration-300 cursor-pointer"
      onClick={() => navigate(`/document/${encodeURIComponent(highlight.doc_id)}`)}
    >
      <DecoIcon className="absolute -right-4 -top-4 w-28 h-28 text-primary/[0.06] pointer-events-none" />
      <div className="relative p-8 flex flex-col h-full justify-between">
        <div>
          <div className="flex items-center gap-3 mb-5">
            <span className="px-2.5 py-1 bg-primary text-white text-[10px] font-bold uppercase tracking-wider rounded">
              {highlight.badge}
            </span>
            <span className="text-xs font-mono text-text-tertiary flex items-center gap-2">
              <SectionBadge section={highlight.section} />
              {highlight.edition_number && <span>Edição {highlight.edition_number}</span>}
            </span>
          </div>
          <h3 className="text-2xl lg:text-3xl font-black leading-tight group-hover:text-primary transition-colors line-clamp-3">
            {highlight.title}
          </h3>
          {highlight.summary && (
            <p className="text-text-secondary text-base leading-relaxed mt-4 line-clamp-3">
              {highlight.summary}
            </p>
          )}
          {highlight.why && (
            <p className="text-sm text-primary/80 mt-3 italic">{highlight.why}</p>
          )}
        </div>
        <div className="mt-8 pt-6 border-t border-border flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-primary">
              <Icons.document className="w-5 h-5" />
            </div>
            <div>
              <p className="text-sm font-semibold line-clamp-1">{highlight.issuing_organ}</p>
              <p className="text-xs text-text-tertiary">{formatDayMonth(highlight.pub_date)}</p>
            </div>
          </div>
          <span className="px-4 py-2 border border-border rounded-lg text-sm font-semibold hover:bg-muted transition-colors">
            Ler Documento
          </span>
        </div>
      </div>
    </div>
  );
};

const CategoryCard: React.FC<{ highlight: EditorialHighlight; category: string }> = ({ highlight, category }) => {
  const navigate = useNavigate();
  const style = CATEGORY_STYLES[category] || CATEGORY_STYLES.politica;

  return (
    <div
      className="bg-card border border-border rounded-2xl p-5 hover:shadow-md transition-all cursor-pointer"
      onClick={() => navigate(`/document/${encodeURIComponent(highlight.doc_id)}`)}
    >
      <div className="flex justify-between items-start mb-3">
        <div className={`p-2 rounded-lg bg-muted ${style.labelColor}`}>
          {style.icon}
        </div>
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${style.badgeClass}`}>
          {highlight.badge}
        </span>
      </div>
      <h4 className="font-bold leading-snug mb-2 line-clamp-2">{highlight.title}</h4>
      <p className="text-sm text-text-secondary line-clamp-2 mb-3">{highlight.summary}</p>
      <div className="flex items-center justify-between text-[10px] font-semibold text-text-tertiary uppercase tracking-wider">
        <span>{highlight.badge}</span>
        <span className="font-mono normal-case">ID: {highlight.doc_id.slice(-4)}</span>
      </div>
    </div>
  );
};

const EditorialHighlights: React.FC<Props> = ({ data }) => {
  const { categories } = data;
  const { destaque, ...sideCategories } = categories;
  const sideCards = Object.entries(sideCategories).filter(
    (entry): entry is [string, EditorialHighlight] => entry[1] != null,
  );

  if (!destaque && sideCards.length === 0) return null;

  return (
    <section className="max-w-6xl mx-auto px-4 pt-10 pb-4">
      <div className="flex justify-between items-end mb-8">
        <div>
          <h2 className="text-2xl font-black tracking-tight">Destaques Editoriais</h2>
          <p className="text-sm text-text-secondary mt-1">
            As publicações e tendências mais relevantes de hoje.
          </p>
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {destaque && (
          <div className="lg:col-span-8">
            <FeaturedCard highlight={destaque} />
          </div>
        )}
        {sideCards.length > 0 && (
          <div className={`${destaque ? 'lg:col-span-4' : 'lg:col-span-12'} space-y-4`}>
            {sideCards.map(([cat, hl]) => (
              <CategoryCard key={cat} highlight={hl} category={cat} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
};

export default EditorialHighlights;
