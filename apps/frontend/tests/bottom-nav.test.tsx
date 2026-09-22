import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BottomNav } from '@/components/common/bottom-nav';

const pathname = vi.hoisted(() => ({ value: '/dashboard' }));

vi.mock('next/navigation', () => ({
  usePathname: () => pathname.value,
}));

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key }),
}));

beforeEach(() => {
  pathname.value = '/dashboard';
});

/**
 * The tab bar is the single rule that decides whether a page's `MobileActionBar`
 * needs `aboveNav`: tab routes keep the bar, detail routes replace it with a back
 * chevron plus their own action bar.
 */
describe('bottom tab bar', () => {
  it('marks only the matching tab route active', () => {
    pathname.value = '/tracker';
    render(<BottomNav />);

    const tracker = screen.getByRole('link', { name: /nav\.tabs\.tracker/ });
    expect(tracker).toHaveAttribute('aria-current', 'page');
    expect(tracker).toHaveClass('bg-black');

    const resumes = screen.getByRole('link', { name: /nav\.tabs\.resumes/ });
    expect(resumes).not.toHaveAttribute('aria-current');
    expect(resumes).not.toHaveClass('bg-black');
  });

  it('keeps the Create slot an action, never an active tab', () => {
    pathname.value = '/tailor';
    const { container } = render(<BottomNav />);
    // /tailor is a detail route, so the bar is absent entirely.
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing on detail routes, the landing page and print routes', () => {
    for (const route of ['/builder', '/resumes/abc', '/compare', '/resume-wizard', '/']) {
      pathname.value = route;
      const { container, unmount } = render(<BottomNav />);
      expect(container, `expected no tab bar on ${route}`).toBeEmptyDOMElement();
      unmount();
    }

    pathname.value = '/print/resumes/abc';
    const { container } = render(<BottomNav />);
    expect(container).toBeEmptyDOMElement();
  });

  it('stays out of the way of the document instead of covering it', () => {
    pathname.value = '/settings';
    render(<BottomNav />);
    const nav = screen.getByRole('navigation');
    // `sticky`, never `fixed`: a fixed bar would silently cover the last row of every list.
    expect(nav).toHaveClass('sticky');
    expect(nav).not.toHaveClass('fixed');
    expect(nav).toHaveClass('lg:hidden');
  });
});
