"""
Testes automatizados que cobrem dois cenários de migração de artigos
relativos à conexão com o Core (pid provider remoto):

1. test_request_pid_when_core_is_unreachable
   - Simula falha de conexão com o Core no momento da migração.
   - Verifica o comportamento *esperado* (correto): a falha do Core deve
     ser propagada e o registro local NÃO deve ser executado, evitando a
     geração de um PID v3 local que mais tarde causa duplicidade quando
     o Core volta. Marcado como ``expectedFailure`` enquanto o bug
     descrito na issue não é corrigido — funciona como documentação
     executável do defeito.

2. test_request_pid_when_core_is_reachable
   - Simula sucesso na conexão com o Core: o PID v3 retornado pelo Core
     é usado também no registro local, e o resultado fica sincronizado
     entre Upload e Core.
"""

import unittest
from unittest.mock import MagicMock, patch

from pid_provider.requester import PidRequester


def _make_xml_with_pre(v3=None, v2="S0034-77442021000600036", aop_pid=None):
    """Cria um stub mínimo de XMLWithPre para uso nos testes."""
    xml = MagicMock()
    xml.v3 = v3
    xml.v2 = v2
    xml.aop_pid = aop_pid
    xml.filename = "0034-7744-rb-2021-00036.xml"
    return xml


class RequestPidForXmlWithPreCoreConnectivityTest(unittest.TestCase):
    """
    Cenários de conectividade com o Core durante a migração.

    A unidade sob teste é ``PidRequester.request_pid_for_xml_with_pre``,
    que orquestra:
        - get_registration_demand (consulta de necessidade de registro)
        - remote_registration     (registro no Core)
        - local_registration      (registro no Upload)

    Estes testes mocam essas três operações para isolar o comportamento
    do orquestrador frente à conectividade com o Core.
    """

    def setUp(self):
        self.user = MagicMock(username="migration_user")
        self.article_proc = MagicMock()
        self.xml_with_pre = _make_xml_with_pre()
        self.requester = PidRequester()

    # -------------------------------------------------------------------
    # Cenário 1: Core indisponível (sem conexão)
    # -------------------------------------------------------------------
    @unittest.expectedFailure
    @patch.object(PidRequester, "local_registration")
    @patch.object(PidRequester, "remote_registration")
    @patch.object(PidRequester, "get_registration_demand")
    def test_request_pid_when_core_is_unreachable(
        self,
        mock_get_demand,
        mock_remote,
        mock_local,
    ):
        """
        Quando o Core está indisponível na migração, ``remote_registration``
        retorna um dicionário com ``error_type``/``error_msg``.

        Comportamento esperado (após correção do bug descrito na issue):
            - O orquestrador deve interromper o fluxo e retornar o erro,
              sem invocar ``local_registration``.
            - Isso evita a criação de um PID v3 local sem contraparte no
              Core, que é a causa raiz das duplicações observadas após o
              restabelecimento da conexão.

        Comportamento atual (bug):
            - ``remote_registration`` retorna o erro em ``remote_response``
              mas NÃO atualiza o dicionário ``registered``; o teste de
              ``registered.get("error_type")`` falha em detectar o erro
              e ``local_registration`` é chamado mesmo assim,
              gerando um PID v3 local.

        Este teste é marcado com ``expectedFailure`` para deixar o defeito
        documentado de forma executável até a correção ser aplicada.
        """
        # Demanda de registro: precisa registrar nos dois lados
        mock_get_demand.return_value = {
            "do_remote_registration": True,
            "do_local_registration": True,
        }

        # Core indisponível: remote_registration devolve dict de erro
        # (este é exatamente o formato real produzido pelo bloco except
        # de PidRequester.remote_registration, ll. 210-213).
        core_error = {
            "error_msg": "Connection refused: Core unreachable",
            "error_type": "<class 'ConnectionError'>",
        }
        mock_remote.return_value = core_error

        result = self.requester.request_pid_for_xml_with_pre(
            self.xml_with_pre,
            name="0034-7744-rb-2021-00036.xml",
            user=self.user,
            article_proc=self.article_proc,
        )

        # 1) O Core foi consultado uma vez
        mock_remote.assert_called_once()

        # 2) Local registration NÃO deve ser chamado quando Core falhou,
        #    pois isso geraria PID v3 local e causaria a duplicação
        #    descrita na issue.
        mock_local.assert_not_called()

        # 3) O erro do Core deve ser propagado para o chamador.
        self.assertIn("error_type", result)
        self.assertEqual(
            result["error_type"], "<class 'ConnectionError'>"
        )

    # -------------------------------------------------------------------
    # Cenário 2: Core disponível (com conexão) — caminho feliz
    # -------------------------------------------------------------------
    @patch.object(PidRequester, "local_registration")
    @patch.object(PidRequester, "remote_registration")
    @patch.object(PidRequester, "get_registration_demand")
    def test_request_pid_when_core_is_reachable(
        self,
        mock_get_demand,
        mock_remote,
        mock_local,
    ):
        """
        Quando o Core está disponível na migração:
            - ``remote_registration`` devolve o PID v3 emitido pelo Core
              e atualiza o dicionário ``registered`` com
              ``registered_in_core=True``.
            - ``local_registration`` é chamado em seguida, gravando o
              mesmo PID v3 no Upload e marcando ``synchronized=True``.
            - O resultado retornado contém o PID v3 do Core, sem
              ``error_type``.
        """
        # Demanda de registro: precisa registrar nos dois lados
        registered_state = {
            "do_remote_registration": True,
            "do_local_registration": True,
        }
        mock_get_demand.return_value = registered_state

        core_pid_v3 = "SJLD63mRxz9nTXtyMj7SLwk"

        # remote_registration: simula resposta de sucesso do Core,
        # incluindo a atualização in-place de ``registered`` que o
        # método real executa (ver requester.py l. 208).
        def fake_remote(user, article_proc, xml_with_pre, registered):
            response = {
                "v3": core_pid_v3,
                "v2": "S0034-77442021000600036",
                "aop_pid": None,
                "pkg_name": "0034-7744-rb-2021-00036",
                "registered_in_core": True,
                "do_local_registration": True,
            }
            registered.update(response)
            return response

        mock_remote.side_effect = fake_remote

        # local_registration: simula sucesso do registro no Upload,
        # também atualizando ``registered`` (ver requester.py l. 255).
        def fake_local(
            user, article_proc, xml_with_pre, registered,
            origin_date, force_update, is_published, origin,
        ):
            response = {
                "v3": core_pid_v3,
                "registered_in_upload": True,
                "synchronized": True,
            }
            registered.update(response)
            return response

        mock_local.side_effect = fake_local

        result = self.requester.request_pid_for_xml_with_pre(
            self.xml_with_pre,
            name="0034-7744-rb-2021-00036.xml",
            user=self.user,
            article_proc=self.article_proc,
        )

        # 1) Core e Upload foram chamados, na ordem esperada.
        mock_remote.assert_called_once()
        mock_local.assert_called_once()

        # 2) Sem erro propagado.
        self.assertNotIn("error_type", result)

        # 3) O PID v3 retornado é o emitido pelo Core (não um PID local).
        self.assertEqual(result["v3"], core_pid_v3)

        # 4) Estado final indica sincronização entre Upload e Core,
        #    que é a invariante que evita a duplicação posterior.
        self.assertTrue(result.get("registered_in_core"))
        self.assertTrue(result.get("registered_in_upload"))
        self.assertTrue(result.get("synchronized"))

        # 5) Metadados auxiliares preenchidos pelo orquestrador.
        self.assertIs(result["xml_with_pre"], self.xml_with_pre)
        self.assertEqual(result["filename"], "0034-7744-rb-2021-00036.xml")


if __name__ == "__main__":
    unittest.main()
