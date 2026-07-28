from __future__ import annotations
from moughorai.security_analysis import Severity
from moughorai.security_analysis.rules import TaintRule
from .models import Framework, FrameworkProfile

SPRING_SPEL = TaintRule('ATLAS-SPRING-SPEL-001','Spring expression injection','CWE-917','A03:2021',Severity.HIGH,('ExpressionParser.parseExpression','SpelExpressionParser.parseExpression'))
JPA_QUERY = TaintRule('ATLAS-JPA-QUERY-001','JPA query injection','CWE-89','A03:2021',Severity.CRITICAL,('EntityManager.createQuery','Session.createQuery'))
JACKSON_TYPE = TaintRule('ATLAS-JACKSON-TYPE-001','Unsafe polymorphic deserialization','CWE-502','A08:2021',Severity.HIGH,('ObjectMapper.readValue','ObjectMapper.treeToValue'))
GSON_DESER = TaintRule('ATLAS-GSON-DESER-001','Untrusted Gson deserialization','CWE-502','A08:2021',Severity.MEDIUM,('Gson.fromJson',))

PROFILES = (
 FrameworkProfile(Framework.SPRING_WEB,('org.springframework.web','@RestController','@Controller','@GetMapping','@PostMapping'),('RequestParam','PathVariable','RequestHeader','request.getParameter','ServerWebExchange.getRequest'),('HtmlUtils.htmlEscape','UriUtils.encode'),(SPRING_SPEL,),('GetMapping','PostMapping','PutMapping','DeleteMapping','PatchMapping','RequestMapping')),
 FrameworkProfile(Framework.SPRING_SECURITY,('org.springframework.security','SecurityFilterChain','HttpSecurity'),('Authentication.getName','Principal.getName','Jwt.getClaim'),('PasswordEncoder.encode',),(),()),
 FrameworkProfile(Framework.SERVLET,('jakarta.servlet','javax.servlet','HttpServletRequest','@WebServlet'),('getParameter','getHeader','getQueryString','getInputStream'),(),(),('WebServlet','Path')),
 FrameworkProfile(Framework.JDBC,('java.sql','JdbcTemplate','NamedParameterJdbcTemplate'),(),('PreparedStatement.setString','NamedParameterJdbcTemplate.query'),(),()),
 FrameworkProfile(Framework.JPA,('jakarta.persistence','javax.persistence','EntityManager','org.hibernate'),(),(),(JPA_QUERY,),()),
 FrameworkProfile(Framework.JACKSON,('com.fasterxml.jackson','ObjectMapper'),(),(),(JACKSON_TYPE,),()),
 FrameworkProfile(Framework.GSON,('com.google.gson','Gson'),(),(),(GSON_DESER,),()),
)
