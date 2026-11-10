import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

/** H5: 顶层错误边界，单个组件渲染异常不再导致整页白屏。 */
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    if (import.meta.env.DEV) console.error("未捕获的渲染异常", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ display: "flex", height: "100vh", alignItems: "center", justifyContent: "center" }}>
          <div style={{ textAlign: "center", maxWidth: 480, padding: 24 }}>
            <h2>页面出错了</h2>
            <p style={{ color: "#666", fontSize: 13, wordBreak: "break-all" }}>{this.state.error.message}</p>
            <button onClick={() => window.location.reload()}>重新加载</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
