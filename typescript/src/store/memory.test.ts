import { MemoryTokenStore } from './memory';

describe('MemoryTokenStore', () => {
  it('stores and retrieves values', () => {
    const store = new MemoryTokenStore();
    store.set('a', '1');
    expect(store.get('a')).toBe('1');
    expect(store.get('missing')).toBeUndefined();
  });

  it('expires values past their ttl', () => {
    const store = new MemoryTokenStore();
    const now = Date.now();
    const spy = jest.spyOn(Date, 'now');
    spy.mockReturnValue(now);
    store.set('a', '1', 10); // 10s ttl
    expect(store.get('a')).toBe('1');
    spy.mockReturnValue(now + 11_000);
    expect(store.get('a')).toBeUndefined();
    spy.mockRestore();
  });

  it('deletes keys and lists live keys', () => {
    const store = new MemoryTokenStore();
    store.set('a', '1');
    store.set('b', '2');
    store.delete('a');
    expect(store.list().sort()).toEqual(['b']);
  });

  it('prunes expired keys from list()', () => {
    const store = new MemoryTokenStore();
    const now = Date.now();
    const spy = jest.spyOn(Date, 'now');
    spy.mockReturnValue(now);
    store.set('live', 'x');
    store.set('dead', 'y', 5);
    spy.mockReturnValue(now + 6_000);
    expect(store.list()).toEqual(['live']);
    spy.mockRestore();
  });
});
