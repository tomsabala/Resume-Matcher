import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PageContainer } from '@/components/preview/page-container';
import { mmToPx } from '@/lib/constants/page-dimensions';

/**
 * `transform: scale()` does not change an element's layout box. The A4 page keeps
 * its 793.7px width, so the *wrapper* must carry the scaled width — otherwise a
 * narrow centring parent puts part of the page at negative coordinates, which no
 * scroll container can reach, and the left edge of the resume is unreachable.
 */
describe('PageContainer scaling', () => {
  it('lays the wrapper out at the scaled width while the page keeps full size', () => {
    const scale = 0.33;
    const { container } = render(
      <PageContainer
        pageSize="A4"
        margins={{ top: 10, bottom: 10, left: 10, right: 10 }}
        pageNumber={1}
        totalPages={1}
        scale={scale}
        showMarginGuides={false}
      >
        <p>content</p>
      </PageContainer>
    );

    const wrapper = container.firstElementChild as HTMLElement;
    const page = wrapper.firstElementChild as HTMLElement;

    expect(wrapper.style.width).toBe(`${mmToPx(210) * scale}px`);
    expect(page.style.width).toBe(`${mmToPx(210)}px`);
    expect(page.style.transform).toBe(`scale(${scale})`);
    // A centred origin would push the scaled page back out of the wrapper.
    expect(page).toHaveClass('origin-top-left');
  });
});
