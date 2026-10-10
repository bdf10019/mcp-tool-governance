import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";


beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  cleanup();
});


describe("MCP 工具治理 Showcase", () => {
  it("讓第一次接觸產品的訪客理解水泵與 MCP", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: /AI 可以提議/ })).toBeInTheDocument();
    expect(screen.getByText(/把它想成 AI 使用公司工具的標準插座/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /循環水泵構造示意/ })).toBeInTheDocument();
  });

  it("切換客戶模式會改變欄位與核准人數", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /風險治理/ }));
    expect(screen.getAllByText("廠內設備管理團隊").length).toBeGreaterThan(0);
    expect(screen.getByText("來源證據")).toBeInTheDocument();
    expect(screen.getByText("2 人")).toBeInTheDocument();
  });

  it("可查水泵資料並阻擋跨設備枚舉", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    const toolSection = container.querySelector("#tools") as HTMLElement;
    await user.click(within(toolSection).getByRole("button", { name: /設備狀態/ }));
    await user.click(within(toolSection).getByRole("button", { name: "執行離線示範" }));
    expect(within(toolSection).getByText(/degraded/)).toBeInTheDocument();
    await user.selectOptions(within(toolSection).getByLabelText("設備編號"), "EQ-CHILLER-004");
    await user.click(within(toolSection).getByRole("button", { name: "執行離線示範" }));
    expect(within(toolSection).getByText(/NOT_FOUND_OR_FORBIDDEN/)).toBeInTheDocument();
  });

  it("維修服務商單人核准後重送仍是同一張工單", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    const approval = container.querySelector("#approval") as HTMLElement;
    const idempotency = container.querySelector("#idempotency") as HTMLElement;
    await user.click(within(approval).getByRole("button", { name: "建立並凍結提案" }));
    await user.click(within(approval).getByRole("button", { name: "Reviewer A 核准" }));
    expect(within(approval).getByText(/核准完成/)).toBeInTheDocument();
    await user.click(within(idempotency).getByRole("button", { name: "第一次送出" }));
    await user.click(within(idempotency).getByRole("button", { name: "重送同一請求" }));
    expect(within(idempotency).getAllByText(/WO-DEMO-001/).length).toBeGreaterThan(0);
    expect(within(idempotency).getByText(/沒有第二張工單/)).toBeInTheDocument();
  });

  it("設備管理團隊需要兩名不同 reviewer", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    await user.click(screen.getByRole("button", { name: /風險治理/ }));
    const approval = container.querySelector("#approval") as HTMLElement;
    await user.click(within(approval).getByRole("button", { name: "建立並凍結提案" }));
    await user.click(within(approval).getByRole("button", { name: "Reviewer A 核准" }));
    expect(within(approval).getByText(/仍需另一位不同 reviewer/)).toBeInTheDocument();
    await user.click(within(approval).getByRole("button", { name: "重複 Reviewer A" }));
    expect(within(approval).getByText(/不能重複計數/)).toBeInTheDocument();
    await user.click(within(approval).getByRole("button", { name: "Reviewer B 核准" }));
    expect(within(approval).getByText(/核准完成/)).toBeInTheDocument();
  });

  it("設定差異預覽後才允許離線套用", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    const section = container.querySelector("#configuration") as HTMLElement;
    const apply = within(section).getByRole("button", { name: "模擬核准後套用" });
    expect(apply).toBeDisabled();
    await user.click(within(section).getByRole("button", { name: "預覽差異" }));
    expect(apply).toBeEnabled();
    await user.click(apply);
    expect(within(section).getByText(/真實工作台設定沒有改動/)).toBeInTheDocument();
  });

  it("竄改備份被阻擋，未竄改備份顯示五項零權威", async () => {
    const user = userEvent.setup();
    const { container } = render(<App />);
    const section = container.querySelector("#restore") as HTMLElement;
    const tamper = within(section).getByLabelText("模擬備份遭竄改");
    await user.click(tamper);
    await user.click(within(section).getByRole("button", { name: "建立隔離還原" }));
    expect(within(section).getByText(/checksum 不一致/)).toBeInTheDocument();
    await user.click(tamper);
    await user.click(within(section).getByRole("button", { name: "建立隔離還原" }));
    expect(within(section).getByText("零權威驗證通過")).toBeInTheDocument();
    expect(within(section).getByText(/Session 0/)).toBeInTheDocument();
  });

  it("重置只清除介紹站的瀏覽器狀態", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /風險治理/ }));
    expect(sessionStorage.getItem("mcp-showcase-profile")).toBe("asset");
    await user.click(screen.getByRole("button", { name: "重置示範" }));
    expect(screen.getAllByText("維修服務商").length).toBeGreaterThan(0);
    expect(document.querySelector(".live-region")).toHaveTextContent(/核心產品未被修改/);
  });
});
