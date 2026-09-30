export {};

declare global {
  interface Window {
    kv?: {
      call<T = Record<string, unknown>>(method: string, params?: Record<string, unknown>): Promise<T>;
      cancel(): Promise<boolean>;
      chooseFile(kind: string): Promise<string>;
      chooseFolder(): Promise<string>;
      saveVideo(name: string): Promise<string>;
      openPath(path: string): Promise<string>;
      openExternal(url: string): Promise<void>;
      copyText(value: string): Promise<boolean>;
      mediaUrl(path: string): Promise<string>;
      onProgress(callback: (value: { label: string; percent: number }) => void): () => void;
    };
  }
}
