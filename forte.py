import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import openpyxl
import requests  # mantido (mesmo que não use)

# ===============================
# STREAMLIT CONFIG (SEMPRE NO TOPO)
# ===============================
st.set_page_config(page_title="FORTE FP&A", layout="wide")
st.title("FORTE FP&A")
st.sidebar.image("Assinatura visual 11B.png", use_container_width=True)

# Sidebar visual (igual seu outro projeto)
st.markdown(
    """
    <style>
        section[data-testid="stSidebar"] { background-color: #002d70; }
        section[data-testid="stSidebar"] * { color: white; }
        section[data-testid="stSidebar"] label { color: white; font-weight: 600; }
        section[data-testid="stSidebar"] div[role="radiogroup"] label { color: white; }
        section[data-testid="stSidebar"] .stRadio > div { background: transparent; }
    </style>
    """,
    unsafe_allow_html=True
)

menu = st.sidebar.radio(
    "Navegação",
    ["Dashboard", "Demonstrativo", "Simulação Ajustada"]
)

# ===============================
# 1) BASE
# ===============================
df = pd.read_excel("BASE DRE.xlsx")

df["MÊS"] = pd.to_datetime(df["MÊS"], errors="coerce").dt.to_period("M").dt.to_timestamp()

meses_pt = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr",
    5: "mai", 6: "jun", 7: "jul", 8: "ago",
    9: "set", 10: "out", 11: "nov", 12: "dez"
}
df["MES_FORMATADO"] = (
    df["MÊS"].dt.month.map(meses_pt) + "/" + df["MÊS"].dt.year.astype(str)
)

# ===============================
# 2) PADRONIZAR SINAIS (subtraídos -> NEGATIVOS)
# ===============================
grupos_subtrair = [
    "(-) DEDUÇÕES DA RECEITA ",
    "(-)CUSTOS E DESPESAS VARIÁVEIS",
    "CUSTOS / DESPESAS",
    "DESPESAS NÃO OPERACIONAIS",
    "EMPRESTIMOS",
]

mask_sub = df["GRUPO CONTA"].isin(grupos_subtrair)
df.loc[mask_sub, "VALOR"] = -df.loc[mask_sub, "VALOR"].abs()

mask_rec = df["GRUPO CONTA"] == "Receita Bruta"
df.loc[mask_rec, "VALOR"] = df.loc[mask_rec, "VALOR"].abs()

# ===============================
# 4) DRE ESTRUTURA
# ===============================
def montar_dre_vertical(df_):
    receita = df_[df_["GRUPO CONTA"] == "Receita Bruta"].groupby("MÊS")["VALOR"].sum()
    deducoes = df_[df_["GRUPO CONTA"] == "(-) DEDUÇÕES DA RECEITA "].groupby("MÊS")["VALOR"].sum()
    custos_var = df_[df_["GRUPO CONTA"] == "(-)CUSTOS E DESPESAS VARIÁVEIS"].groupby("MÊS")["VALOR"].sum()
    custos_fixos = df_[df_["GRUPO CONTA"] == "CUSTOS / DESPESAS"].groupby("MÊS")["VALOR"].sum()
    nao_operacional = df_[df_["GRUPO CONTA"] == "DESPESAS NÃO OPERACIONAIS"].groupby("MÊS")["VALOR"].sum()
    emprestimo = df_[df_["GRUPO CONTA"] == "EMPRESTIMOS"].groupby("MÊS")["VALOR"].sum()

    # Como deduções/custos/etc estão NEGATIVOS, aqui é soma:
    margem = receita + deducoes + custos_var
    resultado_operacional = margem + custos_fixos
    resultado_liquido = resultado_operacional + nao_operacional
    saldo_operacional = resultado_liquido + emprestimo

    dre = pd.DataFrame({
        "Receita Bruta": receita,
        "(-) Deduções": deducoes,
        "(-) Custos Variáveis": custos_var,
        "Margem de Contribuição": margem,
        "Custos / Despesas": custos_fixos,
        "Resultado Operacional": resultado_operacional,
        "Resultado Não Operacional": nao_operacional,
        "Resultado Líquido": resultado_liquido,
        "Saldo Operacional": saldo_operacional
    })
    return dre

dre_final = montar_dre_vertical(df).T  # linhas = estrutura, colunas = mês(datetime)

# ===============================
# 5) Renomear colunas para "jan/2025" etc
# ===============================
map_mes = (
    df[["MÊS", "MES_FORMATADO"]]
    .drop_duplicates()
    .sort_values("MÊS")
    .set_index("MÊS")["MES_FORMATADO"]
    .to_dict()
)

dre_final = dre_final.sort_index(axis=1)
dre_final.columns = [map_mes.get(c, str(c)) for c in dre_final.columns]

# ===============================
# 6) Base "estilo Brumed" + AV/AH
# ===============================
dre_base = dre_final.copy()
dre_base.insert(0, "Descrição", dre_base.index)
dre_base = dre_base.reset_index(drop=True)

colunas_meses = [c for c in dre_base.columns if c != "Descrição"]
dre_analise = dre_base.copy()

# AV (%)
for mes in colunas_meses:
    receita_mes = dre_base.loc[dre_base["Descrição"] == "Receita Bruta", mes]
    receita_mes = receita_mes.values[0] if len(receita_mes) else None

    av_col = f"{mes} AV (%)"
    if receita_mes is None or pd.isna(receita_mes) or receita_mes == 0:
        dre_analise[av_col] = pd.NA
    else:
        dre_analise[av_col] = dre_base[mes] / receita_mes * 100

# AH (%)
for i in range(1, len(colunas_meses)):
    mes_atual = colunas_meses[i]
    mes_anterior = colunas_meses[i - 1]

    ah_col = f"{mes_atual} AH (%)"
    base_ant = dre_base[mes_anterior]

    dre_analise[ah_col] = pd.NA
    mask_ok = base_ant.notna() & (base_ant != 0)
    dre_analise.loc[mask_ok, ah_col] = (
        (dre_base.loc[mask_ok, mes_atual] - dre_base.loc[mask_ok, mes_anterior])
        / dre_base.loc[mask_ok, mes_anterior]
        * 100
    )

# Reordenar colunas
colunas_existentes = dre_analise.columns.tolist()
nova_ordem = ["Descrição"]

for mes in colunas_meses:
    if mes in colunas_existentes:
        nova_ordem.append(mes)

    av_col = f"{mes} AV (%)"
    if av_col in colunas_existentes:
        nova_ordem.append(av_col)

    ah_col = f"{mes} AH (%)"
    if ah_col in colunas_existentes:
        nova_ordem.append(ah_col)

dre_analise = dre_analise[nova_ordem]

# ===============================
# 6.1) TOTAL DO ANO + AV% DO TOTAL
# ===============================

# Total do ano por linha (somando apenas colunas de mês)
dre_base["TOTAL_ANO"] = dre_base[colunas_meses].sum(axis=1)

# Receita Bruta total do ano (base do AV%)
receita_total_ano = dre_base.loc[dre_base["Descrição"] == "Receita Bruta", "TOTAL_ANO"].values[0]

# AV do total (uso ABS para ficar intuitivo mesmo com despesas negativas)
dre_base["AV_TOTAL (%)"] = (
    dre_base["TOTAL_ANO"].abs() / abs(receita_total_ano) * 100
    if receita_total_ano not in [0, None] and not pd.isna(receita_total_ano)
    else pd.NA
)

# Leva as colunas para o dre_analise (mesma ordem de linhas)
dre_analise["TOTAL_ANO"] = dre_base["TOTAL_ANO"].values
dre_analise["AV_TOTAL (%)"] = dre_base["AV_TOTAL (%)"].values

# Coloca no final da tabela (se quiser logo após "Descrição", eu ajusto)
dre_analise = dre_analise[[*dre_analise.columns[:-2], "TOTAL_ANO", "AV_TOTAL (%)"]]

# ===============================
# 7) Estilos
# ===============================
def estilo_financeiro(valor):
    if not isinstance(valor, (int, float)):
        return ""
    if pd.isna(valor):
        return ""
    if valor < 0:
        return "color: red;"
    return ""

def formato_contabil(valor):
    if pd.isna(valor):
        return ""
    valor_abs = abs(valor)
    texto = (
        f"R$ {valor_abs:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )
    return f"({texto})" if valor < 0 else texto

def formato_percentual(valor):
    if pd.isna(valor):
        return ""
    valor_abs = abs(valor)
    texto = f"{valor_abs:.1f}%"
    return f"({texto})" if valor < 0 else texto

# inclui TOTAL_ANO como moeda e AV_TOTAL como percentual
colunas_moeda_extra = ["TOTAL_ANO"]
colunas_pct_extra = ["AV_TOTAL (%)"]

styler = (
    dre_analise
    .style
    .applymap(
        estilo_financeiro,
        subset=[col for col in dre_analise.columns if col != "Descrição"]
    )
    .format(
        {
            **{col: formato_contabil for col in colunas_meses},
            **{col: formato_contabil for col in colunas_moeda_extra},
            **{
                col: formato_percentual
                for col in dre_analise.columns
                if "AV (%)" in col or "AH (%)" in col or col in colunas_pct_extra
            },
        }
    )
)

# ===============================
# 8) DASHBOARD (GRÁFICOS)
# ===============================
dre_mensal = dre_final.T.copy()  # index = MES_FORMATADO
dre_mensal = dre_mensal.reset_index().rename(columns={"index": "MES"})

map_mes_inverso = {v: k for k, v in map_mes.items()}
dre_mensal["MÊS_DT"] = dre_mensal["MES"].map(map_mes_inverso)
dre_mensal = dre_mensal.sort_values("MÊS_DT")

# Média móvel cumulativa (expanding) para cada indicador que vamos plotar como linha "resultado"
def mm_cumulativa(s: pd.Series) -> pd.Series:
    return s.expanding(min_periods=1).mean()

dre_mensal["Receita Bruta_MM"] = mm_cumulativa(dre_mensal["Receita Bruta"])
dre_mensal["Margem de Contribuição_MM"] = mm_cumulativa(dre_mensal["Margem de Contribuição"])
dre_mensal["Resultado Operacional_MM"] = mm_cumulativa(dre_mensal["Resultado Operacional"])
dre_mensal["Resultado Líquido_MM"] = mm_cumulativa(dre_mensal["Resultado Líquido"])

if menu == "Dashboard":
    # -------------------------------
    # Receita Bruta + Média móvel
    # -------------------------------
    st.subheader("📈 Receita Bruta (Evolução Mensal) + Média móvel (cumulativa)")

    fig_receita = go.Figure()
    fig_receita.add_trace(go.Scatter(
        x=dre_mensal["MÊS_DT"], y=dre_mensal["Receita Bruta"],
        mode="lines+markers", name="Receita Bruta"
    ))
    fig_receita.add_trace(go.Scatter(
        x=dre_mensal["MÊS_DT"], y=dre_mensal["Receita Bruta_MM"],
        mode="lines+markers", name="Receita Bruta (MM cumulativa)"
    ))
    fig_receita.update_layout(
        hovermode="x unified",
        xaxis_title="Mês",
        yaxis_title="R$",
        legend_title=""
    )
    fig_receita.update_xaxes(tickformat="%b/%Y", tickangle=-45)
    fig_receita.update_yaxes(tickprefix="R$ ", separatethousands=True, rangemode="tozero")
    fig_receita.update_traces(hovertemplate="R$ %{y:,.2f}")
    st.plotly_chart(fig_receita, use_container_width=True)

    # -------------------------------
    # Margem de Contribuição (com MM)
    # -------------------------------
    st.subheader("Composição da Margem de Contribuição")
    col1, col2 = st.columns(2)

    with col1:
        fig_mc = go.Figure()
        fig_mc.add_bar(x=dre_mensal["MÊS_DT"], y=dre_mensal["Receita Bruta"], name="Receita Bruta")
        fig_mc.add_bar(x=dre_mensal["MÊS_DT"], y=dre_mensal["(-) Deduções"], name="(-) Deduções")
        fig_mc.add_bar(x=dre_mensal["MÊS_DT"], y=dre_mensal["(-) Custos Variáveis"], name="(-) Custos Variáveis")

        # Linha do resultado
        fig_mc.add_trace(go.Scatter(
            x=dre_mensal["MÊS_DT"], y=dre_mensal["Margem de Contribuição"],
            mode="lines+markers", name="Margem de Contribuição"
        ))

        # Linha da MM cumulativa do resultado
        fig_mc.add_trace(go.Scatter(
            x=dre_mensal["MÊS_DT"], y=dre_mensal["Margem de Contribuição_MM"],
            mode="lines+markers", name="Margem (MM cumulativa)"
        ))

        fig_mc.update_layout(
            barmode="relative",
            title="📊 Margem de Contribuição - Composição",
            xaxis_title="Mês",
            yaxis_title="R$",
            hovermode="x unified",
            legend_title="Contas"
        )
        fig_mc.update_xaxes(tickformat="%b/%Y", tickangle=-45)
        fig_mc.update_yaxes(rangemode="tozero")
        fig_mc.update_traces(hovertemplate="R$ %{y:,.2f}")
        st.plotly_chart(fig_mc, use_container_width=True)

    with col2:
        df_cv = df[df["GRUPO CONTA"] == "(-)CUSTOS E DESPESAS VARIÁVEIS"].copy()
        df_cv_agg = df_cv.groupby("ESPECIFICA", as_index=False)["VALOR"].sum()
        df_cv_agg["VALOR_ABS"] = df_cv_agg["VALOR"].abs()

        fig_pie_cv = px.pie(
            df_cv_agg[df_cv_agg["VALOR_ABS"] > 0],
            names="ESPECIFICA",
            values="VALOR_ABS",
            title="Distribuição dos Custos/Despesas Variáveis",
            hole=0.35
        )
        fig_pie_cv.update_traces(
            textinfo="none",
            hovertemplate="%{label}: R$ %{value:,.2f} (<b>%{percent}</b>)"
        )
        st.plotly_chart(fig_pie_cv, use_container_width=True)

    # -------------------------------
    # Resultado Operacional (com MM)
    # -------------------------------
    st.subheader("Composição do Resultado Operacional")
    col1, col2 = st.columns(2)

    with col1:
        fig_ro = go.Figure()
        fig_ro.add_bar(x=dre_mensal["MÊS_DT"], y=dre_mensal["Margem de Contribuição"], name="Margem de Contribuição")
        fig_ro.add_bar(x=dre_mensal["MÊS_DT"], y=dre_mensal["Custos / Despesas"], name="Custos / Despesas")

        fig_ro.add_trace(go.Scatter(
            x=dre_mensal["MÊS_DT"], y=dre_mensal["Resultado Operacional"],
            mode="lines+markers", name="Resultado Operacional"
        ))

        fig_ro.add_trace(go.Scatter(
            x=dre_mensal["MÊS_DT"], y=dre_mensal["Resultado Operacional_MM"],
            mode="lines+markers", name="Res. Operacional (MM cumulativa)"
        ))

        fig_ro.update_layout(
            barmode="relative",
            title="📊 Resultado Operacional - Composição",
            xaxis_title="Mês",
            yaxis_title="R$",
            hovermode="x unified",
            legend_title="Contas"
        )
        fig_ro.update_xaxes(tickformat="%b/%Y", tickangle=-45)
        fig_ro.update_yaxes(rangemode="tozero")
        fig_ro.update_traces(hovertemplate="R$ %{y:,.2f}")
        st.plotly_chart(fig_ro, use_container_width=True)

    with col2:
        df_fix = df[df["GRUPO CONTA"] == "CUSTOS / DESPESAS"].copy()
        df_fix_agg = df_fix.groupby("ESPECIFICA", as_index=False)["VALOR"].sum()
        df_fix_agg["VALOR_ABS"] = df_fix_agg["VALOR"].abs()

        fig_pie_fix = px.pie(
            df_fix_agg[df_fix_agg["VALOR_ABS"] > 0],
            names="ESPECIFICA",
            values="VALOR_ABS",
            title="Distribuição de Custos / Despesas",
            hole=0.35
        )
        fig_pie_fix.update_traces(
            textinfo="none",
            hovertemplate="%{label}: R$ %{value:,.2f} (<b>%{percent}</b>)"
        )
        st.plotly_chart(fig_pie_fix, use_container_width=True)

    # -------------------------------
    # Resultado Líquido (com MM)
    # -------------------------------
    st.subheader("Composição do Resultado Líquido")
    col1, col2 = st.columns(2)

    with col1:
        fig_rl = go.Figure()
        fig_rl.add_bar(x=dre_mensal["MÊS_DT"], y=dre_mensal["Resultado Operacional"], name="Resultado Operacional")
        fig_rl.add_bar(x=dre_mensal["MÊS_DT"], y=dre_mensal["Resultado Não Operacional"], name="Resultado Não Operacional")

        fig_rl.add_trace(go.Scatter(
            x=dre_mensal["MÊS_DT"], y=dre_mensal["Resultado Líquido"],
            mode="lines+markers", name="Resultado Líquido"
        ))

        fig_rl.add_trace(go.Scatter(
            x=dre_mensal["MÊS_DT"], y=dre_mensal["Resultado Líquido_MM"],
            mode="lines+markers", name="Res. Líquido (MM cumulativa)"
        ))

        fig_rl.update_layout(
            barmode="relative",
            title="📊 Resultado Líquido - Composição",
            xaxis_title="Mês",
            yaxis_title="R$",
            hovermode="x unified",
            legend_title="Contas"
        )
        fig_rl.update_xaxes(tickformat="%b/%Y", tickangle=-45)
        fig_rl.update_yaxes(rangemode="tozero")
        fig_rl.update_traces(hovertemplate="R$ %{y:,.2f}")
        st.plotly_chart(fig_rl, use_container_width=True)

    with col2:
        df_no = df[df["GRUPO CONTA"] == "DESPESAS NÃO OPERACIONAIS"].copy()
        df_no_agg = df_no.groupby("ESPECIFICA", as_index=False)["VALOR"].sum()
        df_no_agg["VALOR_ABS"] = df_no_agg["VALOR"].abs()

        fig_pie_no = px.pie(
            df_no_agg[df_no_agg["VALOR_ABS"] > 0],
            names="ESPECIFICA",
            values="VALOR_ABS",
            title="Distribuição das Despesas Não Operacionais",
            hole=0.35
        )
        fig_pie_no.update_traces(
            textinfo="none",
            hovertemplate="%{label}: R$ %{value:,.2f} (<b>%{percent}</b>)"
        )
        st.plotly_chart(fig_pie_no, use_container_width=True)

    # ✅ Removido o "último gráfico de evolução" (como você pediu)
    st.subheader("📈 Evolução: Receita, Resultado Operacional e Saldo Operacional")

    fig_evolucao = go.Figure()

    # Receita Bruta (barra)
    fig_evolucao.add_bar(
        x=dre_mensal["MÊS_DT"],
        y=dre_mensal["Receita Bruta"],
        name="Receita Bruta"
    )

    # Resultado Operacional (linha)
    fig_evolucao.add_trace(
        go.Scatter(
            x=dre_mensal["MÊS_DT"],
            y=dre_mensal["Resultado Operacional"],
            mode="lines+markers",
            name="Resultado Operacional"
        )
    )

    # Saldo Operacional (linha)
    fig_evolucao.add_trace(
        go.Scatter(
            x=dre_mensal["MÊS_DT"],
            y=dre_mensal["Saldo Operacional"],
            mode="lines+markers",
            name="Saldo Operacional"
        )
    )

    fig_evolucao.update_layout(
        title="📊 Receita Bruta, Resultado Operacional e Saldo Operacional",
        xaxis_title="Mês",
        yaxis_title="R$",
        hovermode="x unified",
        legend_title="Indicadores",
        barmode="overlay"
    )

    fig_evolucao.update_xaxes(
        tickformat="%b/%Y",
        tickangle=-45
    )

    fig_evolucao.update_yaxes(
        rangemode="tozero",
        tickformat=",.0f"
    )

    fig_evolucao.update_traces(
        hovertemplate="R$ %{y:,.2f}"
    )

    st.plotly_chart(fig_evolucao, use_container_width=True)
# ===============================
# 9) DEMONSTRATIVO (tabela DRE com AV/AH)
# ===============================
if menu == "Demonstrativo":
    st.markdown("---")
    st.subheader("📊 Resumo Anual")

    # ===============================
    # 1) TOTAL ANUAL
    # ===============================
    dre_anual = dre_base[["Descrição"] + colunas_meses].copy()

    # Soma todas as colunas de mês
    dre_anual["Total Ano"] = dre_anual[colunas_meses].sum(axis=1)

    # Base para AV% = Receita Bruta do ano
    receita_total_ano = dre_anual.loc[
        dre_anual["Descrição"] == "Receita Bruta",
        "Total Ano"
    ].values[0]

    # AV% anual
    if receita_total_ano != 0:
        dre_anual["AV (%)"] = (
            dre_anual["Total Ano"].abs() / abs(receita_total_ano) * 100
        )
    else:
        dre_anual["AV (%)"] = pd.NA

    # Mantém apenas as colunas finais
    dre_anual = dre_anual[["Descrição", "Total Ano", "AV (%)"]]

    # ===============================
    # 2) ESTILO
    # ===============================
    styler_anual = (
        dre_anual
        .style
        .applymap(
            estilo_financeiro,
            subset=["Total Ano"]
        )
        .format({
            "Total Ano": formato_contabil,
            "AV (%)": formato_percentual
        })
    )

    st.dataframe(
        styler_anual,
        use_container_width=True,
        hide_index=True
    )

    st.subheader("📊 Demonstração do Resultado (DRE) - Mensal")
    st.dataframe(
        styler,
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")
    st.subheader("📊 Detalhamento por Grupo")

    lista_grupos = sorted(df["GRUPO CONTA"].dropna().unique().tolist())
    grupo_escolhido = st.selectbox("Selecione o Grupo", lista_grupos)

    df_g = df[df["GRUPO CONTA"] == grupo_escolhido].copy()

    if df_g.empty:
        st.info("Não há dados para esse grupo.")
    else:
        # ===============================
        # 1) GRÁFICO DO GRUPO (BARRAS) - evolução mensal
        # ===============================
        grupo_mensal = (
            df_g.groupby("MÊS", as_index=False)["VALOR"]
            .sum()
            .sort_values("MÊS")
        )

        fig_grupo = go.Figure()
        fig_grupo.add_bar(
            x=grupo_mensal["MÊS"],
            y=grupo_mensal["VALOR"].abs(),  # mostra positivo
        )

        fig_grupo.update_layout(
            title=f"Evolução Mensal (Grupo) - {grupo_escolhido}",
            xaxis_title="Mês",
            yaxis_title="R$",
            hovermode="x unified",
            showlegend=False
        )
        fig_grupo.update_xaxes(tickformat="%b/%Y", tickangle=-45)
        fig_grupo.update_yaxes(tickprefix="R$ ", separatethousands=True, rangemode="tozero")
        fig_grupo.update_traces(hovertemplate="R$ %{y:,.2f}")

        st.plotly_chart(fig_grupo, use_container_width=True)

        # ===============================
        # 2) CONTAS ESPECÍFICAS (LINHAS) - evolução histórica
        # ===============================
        st.markdown("### 📈 Evolução Histórica das Contas Específicas")

        base_contas = (
            df_g.groupby(["MÊS", "ESPECIFICA"], as_index=False)["VALOR"]
            .sum()
            .sort_values("MÊS")
        )

        # Lista de contas disponíveis no grupo
        contas_disponiveis = sorted(base_contas["ESPECIFICA"].dropna().unique().tolist())

        # Seleção (padrão: top 5 por impacto total no período)
        top5 = (
            base_contas.assign(VALOR_ABS=base_contas["VALOR"].abs())
            .groupby("ESPECIFICA", as_index=False)["VALOR_ABS"].sum()
            .sort_values("VALOR_ABS", ascending=False)
            .head(5)["ESPECIFICA"]
            .tolist()
        )

        contas_escolhidas = st.multiselect(
            "Selecione as contas específicas (uma linha por conta)",
            options=contas_disponiveis,
            default=top5
        )

        if not contas_escolhidas:
            st.info("Selecione pelo menos 1 conta para exibir o gráfico.")
        else:
            df_plot = base_contas[base_contas["ESPECIFICA"].isin(contas_escolhidas)].copy()
            df_plot["VALOR_PLOT"] = df_plot["VALOR"].abs()  # mostra positivo

            fig_contas_linhas = px.line(
                df_plot,
                x="MÊS",
                y="VALOR_PLOT",
                color="ESPECIFICA",
                markers=True,
                labels={
                    "MÊS": "Mês",
                    "VALOR_PLOT": "R$",
                    "ESPECIFICA": "Conta"
                },
                title=f"Evolução Mensal por Conta — {grupo_escolhido}"
            )

            fig_contas_linhas.update_layout(
                hovermode="x unified",
                legend_title_text=""
            )
            fig_contas_linhas.update_xaxes(tickformat="%b/%Y", tickangle=-45)
            fig_contas_linhas.update_yaxes(tickprefix="R$ ", separatethousands=True, rangemode="tozero")

            # hover monetário bonitinho
            fig_contas_linhas.update_traces(hovertemplate="R$ %{y:,.2f}")

            st.plotly_chart(fig_contas_linhas, use_container_width=True)

### simulação ajustada ###

# ===============================
# SIMULAÇÃO AJUSTADA (BASE)
# ===============================
df_simulacao = pd.DataFrame({
    "Descrição": [
        "Receita Total",
        "Custos e despesas variáveis",
        "Margem de contribuição",
        "Despesas fixas",
        "Resultado Bruto",
        "Despesas Financeiras",
        "IRPJ/CSL",
        "Resultado Líquido",
        "% Variação Resultado"
    ],
    "Resultado Base": [
        780000.00,
        564720.00,
        215280.00,
        175000.00,
        40280.00,
        11700.00,
        9717.20,
        18862.80,
        pd.NA
    ],
    "Simulação 1 - Aumento 20% volume": [
        936000.00,
        677664.00,
        258336.00,
        175000.00,
        83336.00,
        14040.00,
        23560.64,
        45735.36,
        242.46
    ],
    "Simulação 2 - Redução 10% Desp. Fixas": [
        780000.00,
        564720.00,
        215280.00,
        157500.00,
        57780.00,
        11700.00,
        15667.20,
        30412.80,
        161.23
    ],
    "Simulação 3 - Aumento 7% Preço": [
        834600.00,
        576022.20,
        258577.80,
        175000.00,
        83577.80,
        11700.00,
        24438.45,
        47439.35,
        251.50
    ]
})

# Para formatar colunas: moeda vs percentual (só a última linha é %)
col_moeda = [
    "Resultado Base",
    "Simulação 1 - Aumento 20% volume",
    "Simulação 2 - Redução 10% Desp. Fixas",
    "Simulação 3 - Aumento 7% Preço",
]

def formato_contabil(valor):
    if pd.isna(valor):
        return ""
    valor_abs = abs(valor)
    texto = (
        f"R$ {valor_abs:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )
    return f"({texto})" if valor < 0 else texto

def formato_percentual(valor):
    if pd.isna(valor):
        return ""
    return f"{valor:,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")

def estilo_negativo(valor):
    if not isinstance(valor, (int, float)) or pd.isna(valor):
        return ""
    return "color: red;" if valor < 0 else ""

# Styler: formata moeda em tudo, e na linha "% Variação Resultado" formata como %
styler_sim = (
    df_simulacao
    .style
    .applymap(estilo_negativo, subset=col_moeda)
    .format({c: formato_contabil for c in col_moeda})
)

# Ajusta apenas a última linha (percentual) para virar %
idx_pct = df_simulacao.index[df_simulacao["Descrição"] == "% Variação Resultado"]
if len(idx_pct):
    i = idx_pct[0]
    for c in col_moeda:
        styler_sim = styler_sim.format({c: formato_percentual}, subset=pd.IndexSlice[i, [c]])


if menu == "Simulação Ajustada":
    st.subheader("📊 Simulação Ajustada")
    st.caption("Período de 01.06 a 30.06.2023")

    st.markdown(
    styler_sim.hide(axis="index").to_html(),
    unsafe_allow_html=True
)   
