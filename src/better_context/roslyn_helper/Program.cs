using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace BetterContext.Roslyn;

internal sealed class AnalysisRequest
{
    public string Root { get; set; } = "";
    public List<string> Files { get; set; } = [];
    public List<string> References { get; set; } = [];
}

internal sealed class AnalysisResponse
{
    public Dictionary<string, FileAnalysis> Files { get; set; } = [];
    public List<DependencyRecord> Dependencies { get; set; } = [];
    public List<CallRecord> Calls { get; set; } = [];
    public List<string> Diagnostics { get; set; } = [];
    public string Engine { get; set; } = "roslyn";
}

internal sealed class FileAnalysis
{
    public List<SymbolRecord> Symbols { get; set; } = [];
    public List<UsingRecord> Usings { get; set; } = [];
}

internal sealed class SymbolRecord
{
    [JsonIgnore]
    public ISymbol? RoslynSymbol { get; set; }
    [JsonIgnore]
    public SyntaxNode? Syntax { get; set; }
    public string Id { get; set; } = "";
    public string Kind { get; set; } = "";
    public string Name { get; set; } = "";
    public string QualifiedName { get; set; } = "";
    public string Signature { get; set; } = "";
    public int StartLine { get; set; }
    public int EndLine { get; set; }
    public string? ParentId { get; set; }
    public string Accessibility { get; set; } = "";
    public bool IsPublic { get; set; }
    public string? Documentation { get; set; }
    public List<string> Bases { get; set; } = [];
    public string? UnityType { get; set; }
    public bool IsAbstract { get; set; }
    public bool IsStatic { get; set; }
    public bool IsExtension { get; set; }
    public string? ReturnType { get; set; }
    public string SemanticAnchor { get; set; } = "";
}

internal sealed class UsingRecord
{
    public string Module { get; set; } = "";
    public string? Alias { get; set; }
    public bool IsStatic { get; set; }
    public int Line { get; set; }
}

internal sealed class DependencyRecord
{
    public string Source { get; set; } = "";
    public string Target { get; set; } = "";
    public List<string> Kinds { get; set; } = [];
    public List<string> Symbols { get; set; } = [];
    public List<int> Lines { get; set; } = [];
}

internal sealed class CallRecord
{
    public string CallerId { get; set; } = "";
    public string CallerName { get; set; } = "";
    public string Source { get; set; } = "";
    public string CalleeId { get; set; } = "";
    public string CalleeName { get; set; } = "";
    public string Target { get; set; } = "";
    public int Line { get; set; }
    public string Kind { get; set; } = "call";
}

internal static class Program
{
    private static readonly SymbolDisplayFormat SignatureFormat = new(
        typeQualificationStyle: SymbolDisplayTypeQualificationStyle.NameAndContainingTypesAndNamespaces,
        genericsOptions: SymbolDisplayGenericsOptions.IncludeTypeParameters,
        memberOptions: SymbolDisplayMemberOptions.IncludeAccessibility |
                       SymbolDisplayMemberOptions.IncludeModifiers |
                       SymbolDisplayMemberOptions.IncludeContainingType |
                       SymbolDisplayMemberOptions.IncludeParameters |
                       SymbolDisplayMemberOptions.IncludeType |
                       SymbolDisplayMemberOptions.IncludeRef,
        parameterOptions: SymbolDisplayParameterOptions.IncludeType |
                          SymbolDisplayParameterOptions.IncludeName |
                          SymbolDisplayParameterOptions.IncludeDefaultValue |
                          SymbolDisplayParameterOptions.IncludeParamsRefOut,
        miscellaneousOptions: SymbolDisplayMiscellaneousOptions.UseSpecialTypes |
                              SymbolDisplayMiscellaneousOptions.IncludeNullableReferenceTypeModifier);

    private static readonly HashSet<string> UnityBases =
        ["MonoBehaviour", "ScriptableObject", "EditorWindow", "StateMachineBehaviour"];

    public static int Main(string[] args)
    {
        if (args.Length != 1)
        {
            Console.Error.WriteLine("Usage: BetterContext.Roslyn <request.json>");
            return 2;
        }

        try
        {
            var options = JsonOptions();
            var request = JsonSerializer.Deserialize<AnalysisRequest>(File.ReadAllText(args[0]), options)
                          ?? throw new InvalidOperationException("Invalid request JSON.");
            var response = Analyze(request);
            Console.Write(JsonSerializer.Serialize(response, options));
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            return 1;
        }
    }

    private static AnalysisResponse Analyze(AnalysisRequest request)
    {
        var response = new AnalysisResponse();
        var parseOptions = CSharpParseOptions.Default
            .WithLanguageVersion(LanguageVersion.Latest)
            .WithPreprocessorSymbols("UNITY_EDITOR", "UNITY_STANDALONE", "UNITY_2022_3_OR_NEWER");
        var trees = new List<SyntaxTree>();

        foreach (var relativePath in request.Files.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            var normalized = NormalizePath(relativePath);
            var absolute = Path.Combine(request.Root, relativePath.Replace('/', Path.DirectorySeparatorChar));
            try
            {
                var source = File.ReadAllText(absolute);
                trees.Add(CSharpSyntaxTree.ParseText(source, parseOptions, normalized, Encoding.UTF8));
                response.Files[normalized] = new FileAnalysis();
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            {
                response.Diagnostics.Add($"{normalized}: {error.Message}");
            }
        }

        var references = TrustedPlatformReferences().Concat(request.References)
            .Where(File.Exists)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Select(path => MetadataReference.CreateFromFile(path));
        var compilation = CSharpCompilation.Create(
            "BetterContextAnalysis",
            trees,
            references,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary, allowUnsafe: true));

        var recordsBySymbol = new Dictionary<ISymbol, SymbolRecord>(SymbolEqualityComparer.Default);
        var recordsBySyntax = new Dictionary<SyntaxNode, SymbolRecord>();

        foreach (var tree in trees)
        {
            var model = compilation.GetSemanticModel(tree, ignoreAccessibility: true);
            var root = tree.GetRoot();
            var path = NormalizePath(tree.FilePath);
            var file = response.Files[path];
            file.Usings = ExtractUsings(root);

            foreach (var node in DeclarationNodes(root))
            {
                var symbol = GetDeclaredSymbol(model, node);
                if (symbol is null)
                    continue;
                symbol = NormalizeSymbol(symbol);
                var record = CreateSymbolRecord(path, node, symbol);
                file.Symbols.Add(record);
                recordsBySymbol[symbol] = record;
                recordsBySyntax[node] = record;
            }
        }

        foreach (var file in response.Files.Values)
        {
            foreach (var record in file.Symbols)
            {
                var parentSyntax = record.Syntax?.Ancestors().FirstOrDefault(IsTypeDeclaration);
                if (parentSyntax is not null && recordsBySyntax.TryGetValue(parentSyntax, out var parent))
                    record.ParentId = parent.Id;
            }
        }

        var dependencies = new Dictionary<(string Source, string Target), DependencyAccumulator>();
        foreach (var tree in trees)
        {
            var model = compilation.GetSemanticModel(tree, ignoreAccessibility: true);
            var root = tree.GetRoot();
            var sourcePath = NormalizePath(tree.FilePath);
            ExtractDependencies(model, root, sourcePath, recordsBySymbol, dependencies);
            ExtractCalls(model, root, sourcePath, recordsBySymbol, response.Calls);
            foreach (var diagnostic in tree.GetDiagnostics().Where(item => item.Severity == DiagnosticSeverity.Error))
                response.Diagnostics.Add($"{sourcePath}:{diagnostic.Location.GetLineSpan().StartLinePosition.Line + 1}: {diagnostic.GetMessage()}");
        }

        response.Dependencies = dependencies.Values
            .OrderBy(item => item.Source, StringComparer.Ordinal)
            .ThenBy(item => item.Target, StringComparer.Ordinal)
            .Select(item => item.ToRecord())
            .ToList();
        response.Calls = response.Calls
            .DistinctBy(item => (item.CallerId, item.CalleeId, item.Line, item.Kind))
            .OrderBy(item => item.Source, StringComparer.Ordinal)
            .ThenBy(item => item.Line)
            .ToList();
        return response;
    }

    private static IEnumerable<string> TrustedPlatformReferences()
    {
        var value = AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string;
        return string.IsNullOrWhiteSpace(value)
            ? []
            : value.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries);
    }

    private static List<UsingRecord> ExtractUsings(SyntaxNode root) => root.DescendantNodes()
        .OfType<UsingDirectiveSyntax>()
        .Select(item => new UsingRecord
        {
            Module = item.Name?.ToString() ?? "",
            Alias = item.Alias?.Name.Identifier.ValueText,
            IsStatic = item.StaticKeyword.IsKind(SyntaxKind.StaticKeyword),
            Line = Line(item)
        })
        .Where(item => item.Module.Length > 0)
        .ToList();

    private static IEnumerable<SyntaxNode> DeclarationNodes(SyntaxNode root) =>
        root.DescendantNodes().Where(node => node is BaseTypeDeclarationSyntax
            or DelegateDeclarationSyntax
            or MethodDeclarationSyntax
            or ConstructorDeclarationSyntax
            or PropertyDeclarationSyntax
            or EventDeclarationSyntax
            or EventFieldDeclarationSyntax
            or OperatorDeclarationSyntax
            or ConversionOperatorDeclarationSyntax
            or IndexerDeclarationSyntax
            or LocalFunctionStatementSyntax);

    private static bool IsTypeDeclaration(SyntaxNode node) =>
        node is BaseTypeDeclarationSyntax or DelegateDeclarationSyntax;

    private static ISymbol? GetDeclaredSymbol(SemanticModel model, SyntaxNode node) => node switch
    {
        BaseTypeDeclarationSyntax value => model.GetDeclaredSymbol(value),
        DelegateDeclarationSyntax value => model.GetDeclaredSymbol(value),
        MethodDeclarationSyntax value => model.GetDeclaredSymbol(value),
        ConstructorDeclarationSyntax value => model.GetDeclaredSymbol(value),
        PropertyDeclarationSyntax value => model.GetDeclaredSymbol(value),
        EventDeclarationSyntax value => model.GetDeclaredSymbol(value),
        EventFieldDeclarationSyntax value => value.Declaration.Variables.Count > 0
            ? model.GetDeclaredSymbol(value.Declaration.Variables[0])
            : null,
        OperatorDeclarationSyntax value => model.GetDeclaredSymbol(value),
        ConversionOperatorDeclarationSyntax value => model.GetDeclaredSymbol(value),
        IndexerDeclarationSyntax value => model.GetDeclaredSymbol(value),
        LocalFunctionStatementSyntax value => model.GetDeclaredSymbol(value),
        _ => null
    };

    private static SymbolRecord CreateSymbolRecord(string path, SyntaxNode node, ISymbol symbol)
    {
        var kind = ChunkKind(node, symbol);
        var name = DisplayName(node, symbol);
        var bases = new List<string>();
        string? unityType = null;
        if (symbol is INamedTypeSymbol named)
        {
            if (named.BaseType is not null && named.BaseType.SpecialType != SpecialType.System_Object)
                bases.Add(named.BaseType.ToDisplayString());
            bases.AddRange(named.Interfaces.Select(item => item.ToDisplayString()));
        }
        if (node is BaseTypeDeclarationSyntax typeSyntax)
        {
            foreach (var rawBase in typeSyntax.BaseList?.Types.Select(item => item.Type.ToString()) ?? [])
            {
                if (!bases.Contains(rawBase, StringComparer.Ordinal))
                    bases.Add(rawBase);
            }
        }
        unityType = bases.Select(SimpleName).FirstOrDefault(UnityBases.Contains);

        var returnType = symbol switch
        {
            IMethodSymbol method when method.MethodKind != MethodKind.Constructor => method.ReturnType.ToDisplayString(),
            IPropertySymbol property => property.Type.ToDisplayString(),
            IEventSymbol eventSymbol => eventSymbol.Type.ToDisplayString(),
            _ => null
        };
        var span = node.GetLocation().GetLineSpan();
        return new SymbolRecord
        {
            RoslynSymbol = symbol,
            Syntax = node,
            Id = $"{path}:{span.StartLinePosition.Line + 1}:{kind}:{name}",
            Kind = kind,
            Name = name,
            QualifiedName = symbol.ToDisplayString(SymbolDisplayFormat.CSharpErrorMessageFormat),
            Signature = symbol.ToDisplayString(SignatureFormat),
            StartLine = span.StartLinePosition.Line + 1,
            EndLine = span.EndLinePosition.Line + 1,
            Accessibility = symbol.DeclaredAccessibility.ToString().ToLowerInvariant(),
            IsPublic = IsPublicApi(symbol),
            Documentation = CleanDocumentation(symbol.GetDocumentationCommentXml()),
            Bases = bases.Distinct(StringComparer.Ordinal).ToList(),
            UnityType = unityType,
            IsAbstract = symbol.IsAbstract || symbol is INamedTypeSymbol { TypeKind: TypeKind.Interface },
            IsStatic = symbol.IsStatic,
            IsExtension = symbol is IMethodSymbol { IsExtensionMethod: true },
            ReturnType = returnType,
            SemanticAnchor = SemanticAnchor(node, kind, name)
        };
    }

    private static bool IsPublicApi(ISymbol symbol) => symbol.DeclaredAccessibility is
        Accessibility.Public or Accessibility.Protected or Accessibility.ProtectedOrInternal;

    private static string ChunkKind(SyntaxNode node, ISymbol symbol) => node switch
    {
        InterfaceDeclarationSyntax => "interface",
        StructDeclarationSyntax => "struct",
        EnumDeclarationSyntax => "enum",
        RecordDeclarationSyntax => "record",
        ClassDeclarationSyntax => "class",
        DelegateDeclarationSyntax => "delegate",
        ConstructorDeclarationSyntax => "constructor",
        PropertyDeclarationSyntax or IndexerDeclarationSyntax => "property",
        EventDeclarationSyntax or EventFieldDeclarationSyntax => "event",
        OperatorDeclarationSyntax or ConversionOperatorDeclarationSyntax => "operator",
        LocalFunctionStatementSyntax => "local_function",
        _ when symbol is IMethodSymbol => "method",
        _ => symbol.Kind.ToString().ToLowerInvariant()
    };

    private static string DisplayName(SyntaxNode node, ISymbol symbol) => node switch
    {
        ConstructorDeclarationSyntax => symbol.ContainingType?.Name ?? symbol.Name,
        OperatorDeclarationSyntax value => $"operator {value.OperatorToken.ValueText}",
        ConversionOperatorDeclarationSyntax value => $"operator {value.ImplicitOrExplicitKeyword.ValueText} {value.Type}",
        IndexerDeclarationSyntax => "this[]",
        _ => symbol.Name
    };

    private static void ExtractDependencies(
        SemanticModel model,
        SyntaxNode root,
        string sourcePath,
        Dictionary<ISymbol, SymbolRecord> recordsBySymbol,
        Dictionary<(string Source, string Target), DependencyAccumulator> dependencies)
    {
        foreach (var node in root.DescendantNodes().Where(item => item is IdentifierNameSyntax or GenericNameSyntax))
        {
            var symbol = model.GetSymbolInfo(node).Symbol;
            if (symbol is IAliasSymbol alias)
                symbol = alias.Target;
            if (symbol is null)
                continue;
            symbol = NormalizeSymbol(symbol);
            // A namespace can be assembled from declarations spread across many
            // source files. Mapping its first source location to a file creates a
            // false dependency (for example, `using UnityEngine` pointing at a
            // project file that declares `namespace UnityEngine.AI`). File-level
            // dependency edges must be backed by a concrete declared symbol.
            if (symbol is INamespaceSymbol)
                continue;
            var targetPath = SourcePath(symbol);
            if (targetPath is null || targetPath.Equals(sourcePath, StringComparison.OrdinalIgnoreCase))
                continue;
            var key = (sourcePath, targetPath);
            if (!dependencies.TryGetValue(key, out var accumulator))
            {
                accumulator = new DependencyAccumulator(sourcePath, targetPath);
                dependencies[key] = accumulator;
            }
            accumulator.Kinds.Add(ReferenceKind(node));
            accumulator.Symbols.Add(symbol.ToDisplayString(SymbolDisplayFormat.CSharpErrorMessageFormat));
            accumulator.Lines.Add(Line(node));
        }
    }

    private static void ExtractCalls(
        SemanticModel model,
        SyntaxNode root,
        string sourcePath,
        Dictionary<ISymbol, SymbolRecord> recordsBySymbol,
        List<CallRecord> calls)
    {
        foreach (var node in root.DescendantNodes().Where(IsCallSyntax))
        {
            var target = model.GetSymbolInfo(node).Symbol;
            if (target is null)
                continue;
            target = NormalizeSymbol(target);
            var caller = model.GetEnclosingSymbol(node.SpanStart);
            if (caller is null)
                continue;
            caller = NormalizeSymbol(caller);
            if (!TryRecord(recordsBySymbol, caller, out var callerRecord) ||
                !TryRecord(recordsBySymbol, target, out var calleeRecord))
                continue;
            var targetPath = SourcePath(target);
            if (targetPath is null)
                continue;
            calls.Add(new CallRecord
            {
                CallerId = callerRecord.Id,
                CallerName = callerRecord.QualifiedName,
                Source = sourcePath,
                CalleeId = calleeRecord.Id,
                CalleeName = calleeRecord.QualifiedName,
                Target = targetPath,
                Line = Line(node),
                Kind = node is ObjectCreationExpressionSyntax or ImplicitObjectCreationExpressionSyntax
                    ? "construct"
                    : node is BinaryExpressionSyntax or PrefixUnaryExpressionSyntax or PostfixUnaryExpressionSyntax or CastExpressionSyntax
                        ? "operator"
                        : "call"
            });
        }
    }

    private static bool IsCallSyntax(SyntaxNode node) => node is InvocationExpressionSyntax
        or ObjectCreationExpressionSyntax
        or ImplicitObjectCreationExpressionSyntax
        or ConstructorInitializerSyntax
        or BinaryExpressionSyntax
        or PrefixUnaryExpressionSyntax
        or PostfixUnaryExpressionSyntax
        or CastExpressionSyntax;

    private static bool TryRecord(
        Dictionary<ISymbol, SymbolRecord> records,
        ISymbol symbol,
        out SymbolRecord record)
    {
        if (records.TryGetValue(symbol, out record!))
            return true;
        if (symbol is IMethodSymbol method && records.TryGetValue(method.OriginalDefinition, out record!))
            return true;
        return false;
    }

    private static ISymbol NormalizeSymbol(ISymbol symbol)
    {
        if (symbol is IMethodSymbol { ReducedFrom: not null } method)
            symbol = method.ReducedFrom;
        return symbol.OriginalDefinition;
    }

    private static string? SourcePath(ISymbol symbol)
    {
        var location = symbol.Locations.FirstOrDefault(item => item.IsInSource);
        if (location?.SourceTree is not null)
            return NormalizePath(location.SourceTree.FilePath);
        if (symbol is IMethodSymbol method)
            return SourcePath(method.ContainingType);
        return symbol.ContainingType is not null ? SourcePath(symbol.ContainingType) : null;
    }

    private static string ReferenceKind(SyntaxNode node)
    {
        if (node.AncestorsAndSelf().OfType<AttributeSyntax>().Any())
            return "attribute";
        if (node.AncestorsAndSelf().OfType<BaseTypeSyntax>().Any())
            return "inheritance";
        if (node.AncestorsAndSelf().OfType<ObjectCreationExpressionSyntax>().Any())
            return "construct";
        var invocation = node.AncestorsAndSelf().OfType<InvocationExpressionSyntax>().FirstOrDefault();
        if (invocation is not null && invocation.Expression.Span.Contains(node.Span))
            return "call";
        if (node.AncestorsAndSelf().OfType<TypeSyntax>().Any())
            return "type";
        if (node.AncestorsAndSelf().OfType<MemberAccessExpressionSyntax>().Any())
            return "member";
        return "reference";
    }

    private static int Line(SyntaxNode node) =>
        node.GetLocation().GetLineSpan().StartLinePosition.Line + 1;

    private static string NormalizePath(string path) => path.Replace('\\', '/');

    private static string SimpleName(string value)
    {
        var withoutGenerics = value.Split('<', 2)[0];
        return withoutGenerics.Split('.').Last();
    }

    private static string? CleanDocumentation(string? xml)
    {
        if (string.IsNullOrWhiteSpace(xml))
            return null;
        var text = Regex.Replace(xml, "<[^>]+>", " ");
        text = System.Net.WebUtility.HtmlDecode(text);
        text = Regex.Replace(text, @"\s+", " ").Trim();
        return text.Length == 0 ? null : text;
    }

    private static string SemanticAnchor(SyntaxNode node, string kind, string name)
    {
        var tokens = node.DescendantTokens(descendIntoTrivia: false).Select(token => token.Kind() switch
        {
            SyntaxKind.StringLiteralToken or SyntaxKind.Utf8StringLiteralToken => "<string>",
            SyntaxKind.NumericLiteralToken => "<number>",
            SyntaxKind.CharacterLiteralToken => "<char>",
            _ => token.ValueText
        });
        var normalized = $"TYPE:{kind}\nNAME:{name}\n{string.Join(" ", tokens)}";
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(normalized));
        return Convert.ToHexString(bytes).ToLowerInvariant()[..16];
    }

    private static JsonSerializerOptions JsonOptions() => new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        WriteIndented = false,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    private sealed class DependencyAccumulator(string source, string target)
    {
        public string Source { get; } = source;
        public string Target { get; } = target;
        public HashSet<string> Kinds { get; } = new(StringComparer.Ordinal);
        public HashSet<string> Symbols { get; } = new(StringComparer.Ordinal);
        public HashSet<int> Lines { get; } = [];

        public DependencyRecord ToRecord() => new()
        {
            Source = Source,
            Target = Target,
            Kinds = Kinds.Order(StringComparer.Ordinal).ToList(),
            Symbols = Symbols.Order(StringComparer.Ordinal).Take(20).ToList(),
            Lines = Lines.Order().Take(20).ToList()
        };
    }
}
