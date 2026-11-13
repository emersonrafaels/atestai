"""Marcação de chamada de ferramenta que vaza do modelo para os textos não chega ao parecer nem ao painel."""

from atest.formatting import plain_language, strip_tool_markup
from atest.llm_schemas import AssessmentText

LEAK = (
    "Recomendo devolver ao fornecedor: o preço está 38% acima do anúncio.</parameter>\n"
    '<parameter name="supplier_message">Enviar a especificação da chapa; justificar o preço.'
)


def test_leaked_field_goes_back_to_its_own_field():
    text = AssessmentText.model_construct(summary=LEAK, supplier_message="")
    out = plain_language(text)
    assert out.summary == "Recomendo devolver ao fornecedor: o preço está 38% acima do anúncio."
    assert out.supplier_message == "Enviar a especificação da chapa; justificar o preço."


def test_leak_never_overwrites_a_filled_field():
    text = AssessmentText.model_construct(summary=LEAK, supplier_message="Mensagem já escrita.")
    out = plain_language(text)
    assert out.supplier_message == "Mensagem já escrita." and "parameter" not in out.summary and "Enviar" not in out.summary


def test_stray_tags_are_removed_and_plain_text_is_untouched():
    assert strip_tool_markup("Item 1 acima da tabela.</parameter>") == "Item 1 acima da tabela."
    assert strip_tool_markup('<invoke name="x">texto</invoke>') == "texto"
    assert strip_tool_markup("Cobrado 4,6 m² < 8 peças; preço > referência") == "Cobrado 4,6 m² < 8 peças; preço > referência"
    assert plain_language({"a": ["ok </parameter>"]}) == {"a": ["ok"]}
